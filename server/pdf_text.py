"""R27 Punkt 107: Einfache Textextraktion aus PDFs – reine Standardbibliothek, KEINE OCR.

Entscheidung: eigene, bewusst kleine Umsetzung statt pypdf. Gründe: Barlage PM verspricht „nur Standardbibliothek“
(Installer/PyInstaller ohne Zusatzpakete), Punkt 107 verlangt ausdrücklich „ohne Zusatzpakete“, und für die Erkennung
genügen Stichwörter, eine Nummer und ein Datum – keine exakte Layout-Treue. Was nicht verstanden wird (Scans,
verschlüsselte PDFs, exotische Filter/Schriften), liefert einfach leeren Text → normales Ablegen.

Unterstützt: klassische und komprimierte Objektlisten (Objekt-Streams), FlateDecode/ASCIIHex/ASCII85, Seitenbaum,
Content-Streams mit Tj / TJ / ' / " / Td / TD / T* / Tm / BT/ET, Form-XObjects (Tiefe ≤ 3), Schriften mit
ToUnicode-CMap (bfchar/bfrange, 1- oder 2-Byte-Codes), sonst WinAnsi (cp1252) inkl. /Differences für gängige
Glyphennamen. Grenzen: Dateigröße, Laufzeit, Seitenzahl, Ausgabelänge.

extrahieren(data: bytes, max_seiten=30, max_zeit=4.0) -> str   (wirft nie; im Zweifel "")
"""
import base64
import binascii
import re
import time
import zlib

MAX_BYTES = 25 * 1024 * 1024
MAX_TEXT = 200_000
MAX_STREAM = 8 * 1024 * 1024


class _Abbruch(Exception):
    pass


# ------------------------------------------------------------------ Lexer (PDF-Objekte)
_WS = b" \t\r\n\x0c\x00"
_DELIM = b"()<>[]{}/%"


class _Ref:
    __slots__ = ("num",)

    def __init__(self, num):
        self.num = num

    def __repr__(self):
        return f"R{self.num}"


class _Name(str):
    pass


class _Op(str):
    pass


def _skip_ws(s, i):
    n = len(s)
    while i < n:
        c = s[i]
        if c in _WS:
            i += 1
        elif c == 0x25:  # % Kommentar
            while i < n and s[i] not in b"\r\n":
                i += 1
        else:
            break
    return i


def _lit_string(s, i):
    """s[i] == '(' → (bytes, neues i)"""
    i += 1
    out = bytearray()
    tiefe, n = 1, len(s)
    while i < n:
        c = s[i]
        if c == 0x5C:  # Backslash
            i += 1
            if i >= n:
                break
            c = s[i]
            esc = {0x6E: 10, 0x72: 13, 0x74: 9, 0x62: 8, 0x66: 12, 0x28: 0x28, 0x29: 0x29, 0x5C: 0x5C}
            if c in esc:
                out.append(esc[c]); i += 1
            elif 0x30 <= c <= 0x37:
                j = i
                while j < n and j < i + 3 and 0x30 <= s[j] <= 0x37:
                    j += 1
                out.append(int(s[i:j], 8) & 0xFF); i = j
            elif c in b"\r\n":
                i += 1
                if c == 0x0D and i < n and s[i] == 0x0A:
                    i += 1
            else:
                out.append(c); i += 1
            continue
        if c == 0x28:
            tiefe += 1
        elif c == 0x29:
            tiefe -= 1
            if tiefe == 0:
                return bytes(out), i + 1
        out.append(c)
        i += 1
    return bytes(out), i


def _hex_string(s, i):
    j = s.find(b">", i + 1)
    if j < 0:
        j = len(s)
    h = re.sub(rb"[^0-9A-Fa-f]", b"", s[i + 1:j])
    if len(h) % 2:
        h += b"0"
    try:
        return binascii.unhexlify(h), j + 1
    except (binascii.Error, ValueError):
        return b"", j + 1


def _token(s, i):
    """→ (token, i). Token: int/float, bytes (String), _Name, _Op, '[' ']' '<<' '>>' oder None am Ende."""
    i = _skip_ws(s, i)
    n = len(s)
    if i >= n:
        return None, i
    c = s[i]
    if c == 0x28:
        return _lit_string(s, i)
    if c == 0x3C:
        if i + 1 < n and s[i + 1] == 0x3C:
            return "<<", i + 2
        return _hex_string(s, i)
    if c == 0x3E:
        if i + 1 < n and s[i + 1] == 0x3E:
            return ">>", i + 2
        return _Op(">"), i + 1
    if c in b"[]{}":
        return chr(c), i + 1
    if c == 0x2F:
        j = i + 1
        while j < n and s[j] not in _WS and s[j] not in _DELIM:
            j += 1
        raw = s[i + 1:j]
        raw = re.sub(rb"#([0-9A-Fa-f]{2})", lambda m: bytes([int(m.group(1), 16)]), raw)
        return _Name(raw.decode("latin-1")), j
    j = i
    while j < n and s[j] not in _WS and s[j] not in _DELIM:
        j += 1
    if j == i:
        return _Op(chr(c)), i + 1
    w = s[i:j]
    try:
        if re.fullmatch(rb"[+-]?\d+", w):
            return int(w), j
        if re.fullmatch(rb"[+-]?(\d+\.\d*|\.\d+|\d+\.)", w):
            return float(w), j
    except ValueError:
        pass
    return _Op(w.decode("latin-1")), j


def _parse_obj(s, i, tiefe=0):
    """Parst ein PDF-Objekt (Dict, Array, Zahl, Ref …) ab i → (wert, i)."""
    if tiefe > 40:
        raise _Abbruch()
    t, i = _token(s, i)
    if t == "<<":
        d = {}
        while True:
            k, j = _token(s, i)
            if k is None or k == ">>":
                return d, j
            if not isinstance(k, _Name):
                i = j
                continue
            v, i = _parse_obj(s, j, tiefe + 1)
            d[str(k)] = v
    if t == "[":
        arr = []
        while True:
            j = _skip_ws(s, i)
            if j >= len(s):
                return arr, j
            if s[j] == 0x5D:
                return arr, j + 1
            v, i = _parse_obj(s, j, tiefe + 1)
            if v is None and i <= j:
                return arr, i + 1
            arr.append(v)
    if isinstance(t, int):  # mögliche Referenz „n g R“
        t2, j = _token(s, i)
        if isinstance(t2, int):
            t3, k = _token(s, j)
            if t3 == "R":
                return _Ref(t), k
        return t, i
    if isinstance(t, _Op):
        if t in ("true", "false"):
            return t == "true", i
        if t == "null":
            return None, i
    return t, i


# ------------------------------------------------------------------ Dokument
_OBJ_RE = re.compile(rb"(\d+)\s+(\d+)\s+obj\b")


class _Pdf:
    def __init__(self, data, frist):
        self.d = data
        self.frist = frist
        self.objs = {}      # num → (dict/wert, stream_bytes|None)
        self._lesen()

    def zeit(self):
        if time.monotonic() > self.frist:
            raise _Abbruch()

    def _stream_roh(self, dic, start):
        s = self.d
        if s[start:start + 2] == b"\r\n":
            start += 2
        elif s[start:start + 1] in (b"\n", b"\r"):
            start += 1
        ln = dic.get("Length")
        if isinstance(ln, int) and 0 <= ln <= MAX_STREAM and s[start + ln:start + ln + 30].lstrip().startswith(b"endstream"):
            return s[start:start + ln]
        e = s.find(b"endstream", start)
        if e < 0:
            return None
        roh = s[start:e]
        return roh[:-2] if roh.endswith(b"\r\n") else (roh[:-1] if roh.endswith((b"\n", b"\r")) else roh)

    def _lesen(self):
        s = self.d
        for m in _OBJ_RE.finditer(s):
            self.zeit()
            num = int(m.group(1))
            try:
                v, i = _parse_obj(s, m.end())
            except (_Abbruch, RecursionError, ValueError, IndexError):
                continue
            stream = None
            j = _skip_ws(s, i)
            if isinstance(v, dict) and s.startswith(b"stream", j):
                stream = self._stream_roh(v, j + 6)
            self.objs[num] = (v, stream)  # spätere Definition (inkrementelles Update) gewinnt
        # Objekt-Streams (PDF 1.5) auspacken – nur Objekte, die nicht direkt definiert sind
        for num, (v, st) in list(self.objs.items()):
            if isinstance(v, dict) and v.get("Type") == "ObjStm" and st is not None:
                self.zeit()
                try:
                    roh = self.dekodieren(v, st)
                    n, first = int(v.get("N") or 0), int(v.get("First") or 0)
                    kopf = roh[:first].split()
                    for k in range(min(n, len(kopf) // 2)):
                        onum, off = int(kopf[2 * k]), int(kopf[2 * k + 1])
                        if onum in self.objs:
                            continue
                        val, _ = _parse_obj(roh, first + off)
                        self.objs[onum] = (val, None)
                except (_Abbruch, RecursionError, ValueError, IndexError, zlib.error):
                    continue

    def get(self, v, tiefe=0):
        while isinstance(v, _Ref) and tiefe < 20:
            v = self.objs.get(v.num, (None, None))[0]
            tiefe += 1
        return v

    def stream(self, ref):
        if not isinstance(ref, _Ref):
            return None
        v, st = self.objs.get(ref.num, (None, None))
        if st is None or not isinstance(v, dict):
            return None
        try:
            return self.dekodieren(v, st)
        except (ValueError, zlib.error, binascii.Error):
            return None

    def dekodieren(self, dic, st):
        filt = self.get(dic.get("Filter"))
        filt = filt if isinstance(filt, list) else ([filt] if filt else [])
        for f in filt:
            f = str(self.get(f) or "")
            if f in ("FlateDecode", "Fl"):
                d = zlib.decompressobj()
                st = d.decompress(st, MAX_STREAM)
            elif f in ("ASCIIHexDecode", "AHx"):
                st = binascii.unhexlify(re.sub(rb"[^0-9A-Fa-f]", b"", st.split(b">")[0]) + b"0" * (len(re.sub(rb"[^0-9A-Fa-f]", b"", st.split(b">")[0])) % 2))
            elif f in ("ASCII85Decode", "A85"):
                t = st.strip()
                t = t[2:] if t.startswith(b"<~") else t
                t = t.split(b"~>")[0]
                st = base64.a85decode(re.sub(rb"\s", b"", t))
            else:  # LZW, DCT, CCITT, JBIG2 … → nicht unterstützt (Bilder/Scans)
                raise ValueError("Filter nicht unterstützt")
        return st

    def verschluesselt(self):
        return bool(re.search(rb"/Encrypt\s", self.d[-4096:]) or re.search(rb"trailer[^/]*<<[^>]*?/Encrypt", self.d)) or \
            any(isinstance(v, dict) and v.get("Type") == "XRef" and "Encrypt" in v for v, _ in self.objs.values())

    def seiten(self, max_seiten):
        """Seiten in Dokumentreihenfolge (Seitenbaum, sonst Objektreihenfolge)."""
        wurzel = None
        for v, _ in self.objs.values():
            if isinstance(v, dict) and v.get("Type") == "Catalog":
                wurzel = self.get(v.get("Pages"))
                break
        out, gesehen = [], set()

        def lauf(knoten, erbe, tiefe):
            if len(out) >= max_seiten or tiefe > 30 or not isinstance(knoten, dict) or id(knoten) in gesehen:
                return
            gesehen.add(id(knoten))
            erbe = {**erbe, **{k: knoten[k] for k in ("Resources",) if k in knoten}}
            if knoten.get("Type") == "Pages" or "Kids" in knoten:
                for k in self.get(knoten.get("Kids")) or []:
                    lauf(self.get(k), erbe, tiefe + 1)
            else:
                out.append({**erbe, **knoten})
        if isinstance(wurzel, dict):
            lauf(wurzel, {}, 0)
        if not out:
            out = [v for v, _ in self.objs.values() if isinstance(v, dict) and v.get("Type") == "Page"][:max_seiten]
        return out


# ------------------------------------------------------------------ Schriften
_GLYPHEN = {"adieresis": "ä", "odieresis": "ö", "udieresis": "ü", "Adieresis": "Ä", "Odieresis": "Ö", "Udieresis": "Ü",
            "germandbls": "ß", "space": " ", "period": ".", "comma": ",", "colon": ":", "semicolon": ";", "hyphen": "-",
            "minus": "-", "endash": "–", "emdash": "—", "slash": "/", "numbersign": "#", "parenleft": "(",
            "parenright": ")", "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
            "seven": "7", "eight": "8", "nine": "9", "eacute": "é", "egrave": "è", "aacute": "á", "agrave": "à",
            "ampersand": "&", "at": "@", "percent": "%", "plus": "+", "equal": "=", "underscore": "_", "quotesingle": "'",
            "quotedbl": '"', "Euro": "€", "section": "§", "degree": "°", "bullet": "•", "quoteright": "’", "quoteleft": "‘",
            "quotedblleft": "“", "quotedblright": "”", "quotedblbase": "„", "asterisk": "*"}


def _glyph(name):
    if name in _GLYPHEN:
        return _GLYPHEN[name]
    if len(name) == 1:
        return name
    m = re.fullmatch(r"uni([0-9A-Fa-f]{4})", name)
    if m:
        return chr(int(m.group(1), 16))
    return ""


def _utf16(b):
    try:
        return b.decode("utf-16-be", "ignore")
    except Exception:
        return ""


class _Schrift:
    def __init__(self, pdf, fdict):
        fdict = pdf.get(fdict) if fdict is not None else None
        fdict = fdict if isinstance(fdict, dict) else {}
        self.zweibyte = fdict.get("Subtype") == "Type0"
        self.cmap = {}
        self.laengen = set()
        self.diff = {}
        tu = fdict.get("ToUnicode")
        if tu is not None:
            roh = pdf.stream(tu)
            if roh:
                self._cmap(roh)
        enc = pdf.get(fdict.get("Encoding"))
        if isinstance(enc, dict):
            code = 0
            for x in pdf.get(enc.get("Differences")) or []:
                if isinstance(x, int):
                    code = x
                elif isinstance(x, _Name):
                    self.diff[code] = _glyph(str(x))
                    code += 1

    def _cmap(self, roh):
        txt = roh
        for m in re.finditer(rb"begincodespacerange(.*?)endcodespacerange", txt, re.S):
            for a in re.findall(rb"<([0-9A-Fa-f]+)>\s*<[0-9A-Fa-f]+>", m.group(1)):
                self.laengen.add(len(a) // 2)
        for m in re.finditer(rb"beginbfchar(.*?)endbfchar", txt, re.S):
            for a, b in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]*)>", m.group(1)):
                self.cmap[int(a, 16)] = _utf16(binascii.unhexlify(b if len(b) % 2 == 0 else b + b"0"))
                self.laengen.add(len(a) // 2)
        for m in re.finditer(rb"beginbfrange(.*?)endbfrange", txt, re.S):
            body = m.group(1)
            for a, z, rest in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(<[0-9A-Fa-f]*>|\[[^\]]*\])", body):
                lo, hi = int(a, 16), int(z, 16)
                if hi - lo > 65535:
                    continue
                self.laengen.add(len(a) // 2)
                if rest.startswith(b"["):
                    for k, h in enumerate(re.findall(rb"<([0-9A-Fa-f]*)>", rest)):
                        if lo + k <= hi:
                            self.cmap[lo + k] = _utf16(binascii.unhexlify(h if len(h) % 2 == 0 else h + b"0"))
                else:
                    h = rest[1:-1]
                    basis = binascii.unhexlify(h if len(h) % 2 == 0 else h + b"0")
                    if not basis:
                        continue
                    pre, last = basis[:-2] if len(basis) >= 2 else b"", int.from_bytes(basis[-2:], "big")
                    for k in range(hi - lo + 1):
                        self.cmap[lo + k] = _utf16(pre + (last + k).to_bytes(2, "big", signed=False)) if last + k < 65536 else ""

    def text(self, b):
        if self.cmap:
            n = 2 if (self.zweibyte or self.laengen == {2}) else 1
            if self.laengen == {1}:
                n = 1
            out = []
            for k in range(0, len(b) - n + 1, n):
                c = int.from_bytes(b[k:k + n], "big")
                out.append(self.cmap.get(c, "" if n == 2 else (self.diff.get(c) or bytes([c]).decode("cp1252", "replace"))))
            return "".join(out)
        if self.zweibyte:  # Identity ohne ToUnicode: nicht lesbar
            return ""
        return "".join(self.diff.get(c) or bytes([c]).decode("cp1252", "replace") for c in b)


# ------------------------------------------------------------------ Content-Streams
def _ressourcen(pdf, res):
    res = pdf.get(res)
    return res if isinstance(res, dict) else {}


class _Ausgabe:
    def __init__(self):
        self.teile = []
        self.laenge = 0

    def add(self, t):
        if not t:
            return
        self.teile.append(t)
        self.laenge += len(t)
        if self.laenge > MAX_TEXT:
            raise _Abbruch()

    def nl(self):
        if self.teile and not self.teile[-1].endswith("\n"):
            self.add("\n")

    def sp(self):
        if self.teile and not self.teile[-1].endswith((" ", "\n")):
            self.add(" ")


def _inhalt(pdf, roh, res, aus, tiefe=0):
    if tiefe > 3 or not roh:
        return
    res = _ressourcen(pdf, res)
    fonts = pdf.get(res.get("Font"))
    fonts = fonts if isinstance(fonts, dict) else {}
    xobj = pdf.get(res.get("XObject"))
    xobj = xobj if isinstance(xobj, dict) else {}
    cache = {}
    schrift = None
    stapel = []
    i, n, zaehler = 0, len(roh), 0
    letzte_y = None
    groesse, skala, lauf = 10.0, 1.0, 0  # Schriftgröße, Tm-Skalierung, Zeichen seit letzter Positionierung

    def ausgeben(txt):
        nonlocal lauf
        aus.add(txt)
        lauf += len(txt)
    while i < n:
        zaehler += 1
        if zaehler % 2000 == 0:
            pdf.zeit()
        try:
            t, j = _parse_obj(roh, i)
        except (_Abbruch, RecursionError, ValueError, IndexError):
            break
        if j <= i:
            j = i + 1
        i = j
        if not isinstance(t, _Op) or t in ("true", "false", "null"):
            stapel.append(t)
            if len(stapel) > 64:
                stapel = stapel[-64:]
            continue
        op = str(t)
        if op == "BI":  # Inline-Bild überspringen
            e = roh.find(b"EI", i)
            while e >= 0 and not (e + 2 >= n or roh[e + 2] in _WS):
                e = roh.find(b"EI", e + 2)
            i = n if e < 0 else e + 2
        elif op == "Tf" and len(stapel) >= 2:
            name = str(stapel[-2])
            if name not in cache:
                cache[name] = _Schrift(pdf, fonts.get(name))
            schrift = cache[name]
            if isinstance(stapel[-1], (int, float)) and stapel[-1]:
                groesse = abs(float(stapel[-1]))
        elif op in ("Tj", "'", '"') and stapel:
            if op != "Tj":
                aus.nl()
            if isinstance(stapel[-1], bytes):
                ausgeben((schrift or _Schrift(pdf, None)).text(stapel[-1]))
        elif op == "TJ" and stapel and isinstance(stapel[-1], list):
            for x in stapel[-1]:
                if isinstance(x, bytes):
                    ausgeben((schrift or _Schrift(pdf, None)).text(x))
                elif isinstance(x, (int, float)) and x < -180:
                    aus.sp()
        elif op in ("Td", "TD") and len(stapel) >= 2:
            ty = stapel[-1] if isinstance(stapel[-1], (int, float)) else 0
            tx = stapel[-2] if isinstance(stapel[-2], (int, float)) else 0
            if abs(ty) > 0.5:
                aus.nl()
            elif tx > (lauf * 0.5 + 0.3) * groesse:  # Lücke größer als der geschätzte Lauf → Wortgrenze
                aus.sp()
            lauf = 0
        elif op == "Tm" and len(stapel) >= 6:
            y = stapel[-1] if isinstance(stapel[-1], (int, float)) else None
            if isinstance(stapel[-6], (int, float)) and stapel[-6]:
                skala = abs(float(stapel[-6]))
            lauf = 0
            if y is not None and letzte_y is not None and abs(y - letzte_y) > 0.5:
                aus.nl()
            elif letzte_y is not None:
                aus.sp()
            letzte_y = y
        elif op == "T*":
            aus.nl()
            lauf = 0
        elif op == "ET":
            aus.sp()
        elif op == "Do" and stapel and isinstance(stapel[-1], _Name):
            ref = xobj.get(str(stapel[-1]))
            v = pdf.get(ref)
            if isinstance(v, dict) and v.get("Subtype") == "Form":
                _inhalt(pdf, pdf.stream(ref), v.get("Resources") or res, aus, tiefe + 1)
        stapel = []


def extrahieren(data, max_seiten=30, max_zeit=4.0):
    """Text eines PDFs (nur eingebetteter Text). Leerer String bei Scans, Fehlern, Verschlüsselung, Zeitüberschreitung."""
    try:
        if not data or len(data) > MAX_BYTES or not bytes(data[:1024]).lstrip().startswith(b"%PDF"):
            return ""
        frist = time.monotonic() + max_zeit
        pdf = _Pdf(bytes(data), frist)
        if pdf.verschluesselt():
            return ""
        aus = _Ausgabe()
        try:
            for s in pdf.seiten(max_seiten):
                pdf.zeit()
                inhalt = pdf.get(s.get("Contents"))
                refs = inhalt if isinstance(inhalt, list) else [s.get("Contents")]
                roh = b"\n".join(x for x in (pdf.stream(r) for r in refs) if x)
                _inhalt(pdf, roh, s.get("Resources"), aus)
                aus.nl()
        except _Abbruch:
            pass
        text = "".join(aus.teile)
        text = re.sub(r"[ \t ]+", " ", text.replace("\x00", ""))
        text = re.sub(r" *\n *", "\n", text)
        return re.sub(r"\n{3,}", "\n\n", text).strip()[:MAX_TEXT]
    except Exception:  # robust: kaputte Dateien dürfen das Ablegen nie stören
        return ""
