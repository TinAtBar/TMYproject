"""R26-E: Passwortschutz für Office-Dateien (xlsx/docx) – ECMA-376 Agile Encryption (AES-256-CBC, SHA-512).

encrypt(daten, passwort) → bytes (OLE/CFB-Container mit EncryptionInfo, EncryptedPackage, DataSpaces)
decrypt(container, passwort) → bytes (Original-Paket) – für Tests/Prüfung; ApiError-freie ValueError bei falschem Passwort.

Eigene Implementierung mit `cryptography` (keine weitere Abhängigkeit) inkl. minimalem CFB-Writer/-Reader
(Version 3, 512-Byte-Sektoren, Mini-Stream für kleine Streams). Spezifikation: [MS-OFFCRYPTO] 2.3.4.10–2.3.4.15,
[MS-CFB].
"""
import base64
import hashlib
import hmac
import os
import struct

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

SPIN = 100000
SEGMENT = 4096
_BK_VERIFIER_INPUT = bytes.fromhex("fea7d2763b4b9e79")
_BK_VERIFIER_HASH = bytes.fromhex("d7aa0f6d3061344e")
_BK_KEY = bytes.fromhex("146e0be7abacd0d6")
_BK_HMAC_KEY = bytes.fromhex("5fb2ad010cb9e1f6")
_BK_HMAC_VALUE = bytes.fromhex("a0677f02b22c8433")


# ------------------------------------------------------------------ Krypto-Hilfen
def _sha(*teile):
    h = hashlib.sha512()
    for t in teile:
        h.update(t)
    return h.digest()


def _aes(key, iv, data, enc=True):
    c = Cipher(algorithms.AES(key), modes.CBC(iv))
    x = c.encryptor() if enc else c.decryptor()
    return x.update(data) + x.finalize()


def _pad(data, n=16):
    return data + b"\0" * (-len(data) % n)


def _fix(b, n, fill=b"\x36"):
    return b[:n] if len(b) >= n else b + fill * (n - len(b))


def _pw_hash(passwort, salt, spin=SPIN):
    h = _sha(salt, passwort.encode("utf-16-le"))
    for i in range(spin):
        h = _sha(struct.pack("<I", i), h)
    return h


def _pw_key(h, block, bits=256):
    return _fix(_sha(h, block), bits // 8)


def _iv(salt, block):
    return _fix(_sha(salt, block), 16)


def _paket_crypt(key, salt, data, enc=True):
    out = []
    for i in range(0, len(data), SEGMENT):
        seg = data[i:i + SEGMENT]
        out.append(_aes(key, _iv(salt, struct.pack("<I", i // SEGMENT)), _pad(seg) if enc else seg, enc))
    return b"".join(out)


# ------------------------------------------------------------------ EncryptionInfo
_NS = 'xmlns="http://schemas.microsoft.com/office/2006/encryption" ' \
      'xmlns:p="http://schemas.microsoft.com/office/2006/keyEncryptor/password" ' \
      'xmlns:c="http://schemas.microsoft.com/office/2006/keyEncryptor/certificate"'
_ALG = 'blockSize="16" keyBits="256" hashSize="64" cipherAlgorithm="AES" cipherChaining="ChainingModeCBC" hashAlgorithm="SHA512"'


def _b64(b):
    return base64.b64encode(b).decode("ascii")


def encrypt(daten, passwort, spin=SPIN):
    """Verschlüsselt ein OOXML-Paket (bytes) mit Passwort → CFB-Container (bytes)."""
    if not passwort:
        raise ValueError("Passwort fehlt")
    secret = os.urandom(32)
    key_salt, pw_salt = os.urandom(16), os.urandom(16)
    paket = struct.pack("<Q", len(daten)) + _paket_crypt(secret, key_salt, daten)
    # Datenintegrität
    hmac_key = os.urandom(64)
    hmac_val = hmac.new(hmac_key, paket, hashlib.sha512).digest()
    enc_hmac_key = _aes(secret, _iv(key_salt, _BK_HMAC_KEY), hmac_key)
    enc_hmac_val = _aes(secret, _iv(key_salt, _BK_HMAC_VALUE), hmac_val)
    # Passwort-Schlüssel
    h = _pw_hash(passwort, pw_salt, spin)
    verifier = os.urandom(16)
    e_vin = _aes(_pw_key(h, _BK_VERIFIER_INPUT), pw_salt, verifier)
    e_vh = _aes(_pw_key(h, _BK_VERIFIER_HASH), pw_salt, _pad(_sha(verifier)))
    e_key = _aes(_pw_key(h, _BK_KEY), pw_salt, secret)
    xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
           f'<encryption {_NS}><keyData saltSize="16" {_ALG} saltValue="{_b64(key_salt)}"/>'
           f'<dataIntegrity encryptedHmacKey="{_b64(enc_hmac_key)}" encryptedHmacValue="{_b64(enc_hmac_val)}"/>'
           '<keyEncryptors><keyEncryptor uri="http://schemas.microsoft.com/office/2006/keyEncryptor/password">'
           f'<p:encryptedKey spinCount="{spin}" saltSize="16" {_ALG} saltValue="{_b64(pw_salt)}" '
           f'encryptedVerifierHashInput="{_b64(e_vin)}" encryptedVerifierHashValue="{_b64(e_vh)}" '
           f'encryptedKeyValue="{_b64(e_key)}"/></keyEncryptor></keyEncryptors></encryption>')
    info = struct.pack("<HHI", 4, 4, 0x40) + xml.encode("utf-8")
    return cfb_schreiben({
        "EncryptionInfo": info,
        "EncryptedPackage": paket,
        "\x06DataSpaces": {
            "Version": _DS_VERSION,
            "DataSpaceMap": _DS_MAP,
            "DataSpaceInfo": {"StrongEncryptionDataSpace": _DS_INFO},
            "TransformInfo": {"StrongEncryptionTransform": {"\x06Primary": _DS_PRIMARY}},
        },
    })


def _attr(xml, name, nach=None):
    import re
    s = xml if nach is None else xml[xml.index(nach):]
    m = re.search(r'\b' + name + r'="([^"]*)"', s)
    if not m:
        raise ValueError(f"EncryptionInfo: {name} fehlt")
    return m.group(1)


def decrypt(container, passwort, integritaet=True):
    """Entschlüsselt einen mit encrypt() (oder Office, Agile/AES/SHA-512) erzeugten Container."""
    streams = cfb_lesen(container)
    info, paket = streams["EncryptionInfo"], streams["EncryptedPackage"]
    if struct.unpack("<HH", info[:4]) != (4, 4):
        raise ValueError("Keine Agile-Verschlüsselung")
    xml = info[8:].decode("utf-8")
    kd = "<keyData"
    if _attr(xml, "hashAlgorithm", kd) != "SHA512" or _attr(xml, "keyBits", kd) != "256":
        raise ValueError("Nur AES-256/SHA-512 unterstützt")
    key_salt = base64.b64decode(_attr(xml, "saltValue", kd))
    pe = "<p:encryptedKey"
    pw_salt = base64.b64decode(_attr(xml, "saltValue", pe))
    spin = int(_attr(xml, "spinCount", pe))
    h = _pw_hash(passwort, pw_salt, spin)
    vin = _aes(_pw_key(h, _BK_VERIFIER_INPUT), pw_salt, base64.b64decode(_attr(xml, "encryptedVerifierHashInput", pe)), False)
    vh = _aes(_pw_key(h, _BK_VERIFIER_HASH), pw_salt, base64.b64decode(_attr(xml, "encryptedVerifierHashValue", pe)), False)
    if _sha(vin[:16])[:64] != vh[:64]:
        raise ValueError("Falsches Passwort")
    secret = _aes(_pw_key(h, _BK_KEY), pw_salt, base64.b64decode(_attr(xml, "encryptedKeyValue", pe)), False)[:32]
    if integritaet:
        hk = _aes(secret, _iv(key_salt, _BK_HMAC_KEY), base64.b64decode(_attr(xml, "encryptedHmacKey")), False)[:64]
        hv = _aes(secret, _iv(key_salt, _BK_HMAC_VALUE), base64.b64decode(_attr(xml, "encryptedHmacValue")), False)[:64]
        if not hmac.compare_digest(hmac.new(hk, paket, hashlib.sha512).digest(), hv):
            raise ValueError("Integritätsprüfung fehlgeschlagen")
    groesse = struct.unpack("<Q", paket[:8])[0]
    roh = paket[8:]
    roh = roh[:len(roh) - len(roh) % 16]  # manche Schreiber hängen Füllbytes an
    return _paket_crypt(secret, key_salt, roh, False)[:groesse]


def ist_verschluesselt(data):
    return data[:8] == _MAGIC


# ------------------------------------------------------------------ DataSpaces ([MS-OFFCRYPTO] 2.1.x, feste Inhalte)
def _u(s):
    b = s.encode("utf-16-le")
    return struct.pack("<I", len(b)) + b + b"\0" * (-len(b) % 4)


_DS_VERSION = _u("Microsoft.Container.DataSpaces") + struct.pack("<HHHHHH", 1, 0, 1, 0, 1, 0)
_ref = struct.pack("<II", 1, 0) + _u("EncryptedPackage") + _u("StrongEncryptionDataSpace")
_DS_MAP = struct.pack("<II", 8, 1) + struct.pack("<I", len(_ref) + 4) + _ref
_DS_INFO = struct.pack("<II", 8, 1) + _u("StrongEncryptionTransform")
_tr = struct.pack("<I", 1) + _u("{FF9A3F03-56EF-4613-BDD5-5A41C1D07246}")
_DS_PRIMARY = (struct.pack("<I", len(_tr) + 4) + _tr + _u("Microsoft.Container.EncryptionTransform")
               + struct.pack("<HHHHHH", 1, 0, 1, 0, 1, 0)
               + struct.pack("<I", 0) + struct.pack("<I", 0) + struct.pack("<I", 0) + struct.pack("<I", 4))


# ------------------------------------------------------------------ CFB-Writer / -Reader
_MAGIC = bytes.fromhex("d0cf11e0a1b11ae1")
FREE, ENDC, FATSECT = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD
NOSTREAM = 0xFFFFFFFF
SS, MSS, CUTOFF = 512, 64, 4096


def _cfb_key(name):
    return (len(name), name.upper())


def cfb_schreiben(baum):
    """baum: {name: bytes | {unterbaum}} → CFB-Datei (Version 3)."""
    eintraege = [{"name": "Root Entry", "typ": 5, "data": b"", "kinder": []}]

    def add(d, parent):
        for name in sorted(d, key=_cfb_key):
            v = d[name]
            e = {"name": name, "typ": 1 if isinstance(v, dict) else 2, "data": b"" if isinstance(v, dict) else v, "kinder": []}
            eintraege.append(e)
            parent["kinder"].append(len(eintraege) - 1)
            if isinstance(v, dict):
                add(v, e)
    add(baum, eintraege[0])
    for e in eintraege:
        e.update(left=NOSTREAM, right=NOSTREAM, child=NOSTREAM, color=1, start=ENDC, size=0)

    def tree(ids, tiefe, maxtiefe):  # balancierter Baum; tiefste Ebene rot (gültiger Rot-Schwarz-Baum)
        if not ids:
            return NOSTREAM
        m = len(ids) // 2
        e = eintraege[ids[m]]
        e["left"] = tree(ids[:m], tiefe + 1, maxtiefe)
        e["right"] = tree(ids[m + 1:], tiefe + 1, maxtiefe)
        e["color"] = 0 if (tiefe == maxtiefe and maxtiefe > 0) else 1
        return ids[m]

    def maxt(n):
        t = -1
        while n > 0:
            n //= 2
            t += 1
        return t

    def perfekt(n):
        return (n + 1) & n == 0
    for e in eintraege:
        if e["kinder"]:
            k = e["kinder"]
            e["child"] = tree(k, 0, maxt(len(k)) if not perfekt(len(k)) else -1)

    # Mini-Stream
    mini, minifat = bytearray(), []
    gross = []
    for e in eintraege[1:]:
        if e["typ"] != 2:
            continue
        e["size"] = len(e["data"])
        if not e["data"]:
            e["start"] = ENDC
        elif len(e["data"]) < CUTOFF:
            n = -(-len(e["data"]) // MSS)
            s0 = len(minifat)
            e["start"] = s0
            minifat.extend(list(range(s0 + 1, s0 + n)) + [ENDC])
            mini += e["data"] + b"\0" * (n * MSS - len(e["data"]))
        else:
            gross.append(e)
    # Sektor-Belegung
    sektoren, fat = [], []

    def chain(data):
        if not data:
            return ENDC
        n = -(-len(data) // SS)
        s0 = len(sektoren)
        for i in range(n):
            sektoren.append(data[i * SS:(i + 1) * SS].ljust(SS, b"\0"))
        fat.extend(list(range(s0 + 1, s0 + n)) + [ENDC])
        return s0
    for e in gross:
        e["start"] = chain(e["data"])
    eintraege[0]["start"] = chain(bytes(mini))
    eintraege[0]["size"] = len(mini)
    mf_start = chain(b"".join(struct.pack("<I", x) for x in minifat)) if minifat else ENDC
    n_mf = -(-len(minifat) * 4 // SS) if minifat else 0
    dir_bytes = bytearray()
    for e in eintraege:
        nm = e["name"].encode("utf-16-le")
        if len(nm) > 62:
            raise ValueError("Name zu lang")
        dir_bytes += (nm + b"\0\0").ljust(64, b"\0") + struct.pack("<HBB", len(nm) + 2, e["typ"], e["color"])
        dir_bytes += struct.pack("<III", e["left"], e["right"], e["child"]) + b"\0" * 16 + struct.pack("<I", 0)
        dir_bytes += struct.pack("<QQ", 0, 0) + struct.pack("<IQ", e["start"] if e["typ"] != 1 else 0, e["size"])
    while len(dir_bytes) % SS:
        dir_bytes += (b"\0" * 64 + struct.pack("<HBB", 0, 0, 0) + struct.pack("<III", NOSTREAM, NOSTREAM, NOSTREAM)
                      + b"\0" * 16 + b"\0" * 4 + b"\0" * 16 + b"\0" * 12)
    dir_start = chain(bytes(dir_bytes))
    n_fat = 1
    while n_fat * (SS // 4) < len(sektoren) + n_fat:
        n_fat += 1
    if n_fat > 109:
        raise ValueError("Datei zu groß für den einfachen CFB-Writer")
    fat_start = len(sektoren)
    fat.extend([FATSECT] * n_fat)
    fat.extend([FREE] * (n_fat * (SS // 4) - len(fat)))
    fb = b"".join(struct.pack("<I", x) for x in fat)
    for i in range(n_fat):
        sektoren.append(fb[i * SS:(i + 1) * SS])
    difat = [fat_start + i for i in range(n_fat)] + [FREE] * (109 - n_fat)
    kopf = (_MAGIC + b"\0" * 16 + struct.pack("<HHHHH", 0x3E, 3, 0xFFFE, 9, 6) + b"\0" * 6
            + struct.pack("<IIIIIIIII", 0, n_fat, dir_start, 0, CUTOFF, mf_start, n_mf, ENDC, 0)
            + b"".join(struct.pack("<I", x) for x in difat))
    assert len(kopf) == SS
    return kopf + b"".join(sektoren)


def cfb_lesen(data):
    """Minimaler CFB-Leser → {pfad: bytes} (Pfade mit „/“, nur Streams). Nur Kopf-DIFAT (≤ 109 FAT-Sektoren)."""
    if data[:8] != _MAGIC:
        raise ValueError("Keine OLE/CFB-Datei")
    shift = struct.unpack("<H", data[30:32])[0]
    ss = 1 << shift
    n_fat, dir_start, _, cutoff, mf_start, n_mf, difat_start, n_difat = struct.unpack("<IIIIIIII", data[44:76])
    difat = list(struct.unpack("<109I", data[76:512]))[:n_fat]

    def sek(i):
        o = ss + i * ss if ss == 512 else ss * (i + 1)
        return data[o:o + ss]
    fat = []
    for s in difat:
        fat.extend(struct.unpack(f"<{ss // 4}I", sek(s)))

    def kette(start, f, lese, gr):
        out, s, n = [], start, 0
        while s not in (ENDC, FREE) and n < 10 ** 7:
            out.append(lese(s))
            s = f[s]
            n += 1
        return b"".join(out)
    dirs = kette(dir_start, fat, sek, ss)
    ents = []
    for i in range(0, len(dirs), 128):
        d = dirs[i:i + 128]
        nl = struct.unpack("<H", d[64:66])[0]
        name = d[:max(0, nl - 2)].decode("utf-16-le")
        typ = d[66]
        left, right, child = struct.unpack("<III", d[68:80])
        start, size = struct.unpack("<IQ", d[116:128])
        ents.append({"name": name, "typ": typ, "left": left, "right": right, "child": child, "start": start, "size": size})
    root = ents[0]
    ministream = kette(root["start"], fat, sek, ss)[:root["size"]] if root["start"] != ENDC else b""
    minifat_b = kette(mf_start, fat, sek, ss) if n_mf else b""
    minifat = list(struct.unpack(f"<{len(minifat_b) // 4}I", minifat_b)) if minifat_b else []
    out = {}

    def walk(idx, pfad):
        if idx == NOSTREAM or idx >= len(ents):
            return
        e = ents[idx]
        walk(e["left"], pfad)
        walk(e["right"], pfad)
        p = pfad + e["name"]
        if e["typ"] == 2:
            if e["size"] < cutoff:
                b = kette(e["start"], minifat, lambda s: ministream[s * 64:(s + 1) * 64], 64)
            else:
                b = kette(e["start"], fat, sek, ss)
            out[p] = b[:e["size"]]
        elif e["typ"] == 1:
            walk(e["child"], p + "/")
    walk(root["child"], "")
    return out
