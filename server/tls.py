"""mobile: Firmen-CA, Serverzertifikat und iOS-Profil.

Datenordner/tls/: ca.crt, ca.key (0600), server.crt, server.key (0600), server.json (für welche Namen/IPs).
Nutzt das Paket `cryptography`; fehlt es, liefert verfuegbar() False und der Server bleibt bei HTTP.
"""
import datetime as _dt
import ipaddress
import os
import plistlib
import socket
import ssl
import uuid
import json
from pathlib import Path

try:
    from cryptography import x509
    from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    HAVE_CRYPTO = True
except ImportError:  # pragma: no cover
    HAVE_CRYPTO = False

MDNS_NAME = "opl.local"
CA_NAME = "Barlage PM Firmen-CA"


def verfuegbar():
    return HAVE_CRYPTO


def tls_dir(data_dir):
    d = Path(data_dir) / "tls"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _schreiben(pfad, data, geheim=False):
    tmp = pfad.with_suffix(pfad.suffix + ".tmp")
    with open(tmp, "wb") as f:
        f.write(data)
    if geheim:
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
    os.replace(tmp, pfad)


def _key_pem(key):
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())


def ensure_ca(data_dir):
    """Legt die Firmen-CA einmalig an. Gibt (cert, key) zurück."""
    d = tls_dir(data_dir)
    crt, key = d / "ca.crt", d / "ca.key"
    if crt.exists() and key.exists():
        return (x509.load_pem_x509_certificate(crt.read_bytes()),
                serialization.load_pem_private_key(key.read_bytes(), None))
    k = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, CA_NAME),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Barlage PM")])
    jetzt = _dt.datetime.now(_dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(k.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(jetzt - _dt.timedelta(days=1)).not_valid_after(jetzt + _dt.timedelta(days=3650 * 2))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True, content_commitment=False,
                                         key_encipherment=False, data_encipherment=False, key_agreement=False,
                                         encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(k.public_key()), critical=False)
            .sign(k, hashes.SHA256()))
    _schreiben(key, _key_pem(k), geheim=True)
    _schreiben(crt, cert.public_bytes(serialization.Encoding.PEM))
    return cert, k


def ipv4_adressen(hostname=None):
    """Alle IPv4-Adressen dieses PCs (Hostname-Auflösung + LAN-Route), ohne 0.0.0.0."""
    from election import lan_ip
    ips = {"127.0.0.1"}
    try:
        ips.add(lan_ip())
    except OSError:
        pass
    h = hostname or socket.gethostname()
    for name in filter(None, {h, h.split(".")[0] if h else None}):
        try:
            for fam, *_r, sa in socket.getaddrinfo(name, None, socket.AF_INET):
                ips.add(sa[0])
        except OSError:
            pass
    try:
        ips.update(socket.gethostbyname_ex(h)[2])
    except OSError:
        pass
    out = set()
    for i in ips:
        try:
            a = ipaddress.ip_address(i)
        except ValueError:
            continue
        if a.version == 4 and not a.is_unspecified:
            out.add(str(a))
    return sorted(out)


def standard_namen(hostname=None, ips=None):
    """SAN-Inhalt: opl.local, localhost, Hostname (kurz + FQDN + .local) und alle IPv4-Adressen."""
    namen = {MDNS_NAME, "localhost"}
    h = hostname if hostname is not None else socket.gethostname()
    if h:
        namen.add(h)
        kurz = h.split(".")[0]
        namen.add(kurz)
        namen.add(kurz + ".local")
        try:
            fq = socket.getfqdn(h)
            if fq and "." in fq and not fq.endswith(".arpa"):
                namen.add(fq)
        except OSError:
            pass
    ips = ips if ips is not None else ipv4_adressen(h)
    return sorted(n for n in namen if n), sorted(set(ips))


def san_auslesen(crt_pfad):
    """(dns_namen, ips) aus einem Zertifikat – für Tests/Diagnose."""
    c = x509.load_pem_x509_certificate(Path(crt_pfad).read_bytes())
    san = c.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    return sorted(san.get_values_for_type(x509.DNSName)), sorted(str(i) for i in san.get_values_for_type(x509.IPAddress))


def ca_name(data_dir):
    """Anzeigename (CN) der vorhandenen Firmen-CA – wird aus dem vorhandenen Zertifikat gelesen, nie umbenannt."""
    try:
        c = x509.load_pem_x509_certificate((tls_dir(data_dir) / "ca.crt").read_bytes())
        return c.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
    except Exception:
        return CA_NAME


def ensure_server_cert(data_dir, namen=None, ips=None):
    """Erzeugt/erneuert server.crt, wenn Namen/IPs (Server-Host) sich geändert haben. Gibt (crt_pfad, key_pfad)."""
    d = tls_dir(data_dir)
    if namen is None or ips is None:
        n2, i2 = standard_namen()
        namen, ips = namen or n2, ips or i2
    namen, ips = sorted(set(namen) | {MDNS_NAME}), sorted(set(ips))
    crt, key, info = d / "server.crt", d / "server.key", d / "server.json"
    try:
        alt = json.loads(info.read_text("utf-8"))
        if alt.get("namen") == namen and alt.get("ips") == ips and crt.exists() and key.exists():
            c = x509.load_pem_x509_certificate(crt.read_bytes())
            if c.not_valid_after_utc > _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=30):
                return crt, key
    except (OSError, ValueError, AttributeError):
        pass
    ca_cert, ca_key = ensure_ca(data_dir)
    k = ec.generate_private_key(ec.SECP256R1())
    jetzt = _dt.datetime.now(_dt.timezone.utc)
    san = [x509.DNSName(n) for n in namen] + [x509.IPAddress(ipaddress.ip_address(i)) for i in ips]
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, MDNS_NAME)]))
            .issuer_name(ca_cert.subject).public_key(k.public_key()).serial_number(x509.random_serial_number())
            # iOS: max. 825 Tage für TLS-Serverzertifikate
            .not_valid_before(jetzt - _dt.timedelta(days=1)).not_valid_after(jetzt + _dt.timedelta(days=820))
            .add_extension(x509.SubjectAlternativeName(san), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    _schreiben(key, _key_pem(k), geheim=True)
    _schreiben(crt, cert.public_bytes(serialization.Encoding.PEM) + ca_cert.public_bytes(serialization.Encoding.PEM))
    _schreiben(info, json.dumps({"namen": namen, "ips": ips}).encode())
    return crt, key


def ssl_context(data_dir):
    crt, key = ensure_server_cert(data_dir)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(str(crt), str(key))
    return ctx


class ZertifikatWaechter:
    """Prüft regelmäßig, ob sich Hostname/IP-Adressen geändert haben (z. B. DHCP, WLAN→LAN), stellt dann
    server.crt neu aus und lädt es in den laufenden SSL-Kontext (gilt für neue Verbindungen)."""

    def __init__(self, data_dir, ctx, intervall=60, on_neu=None):
        import threading
        self.data_dir, self.ctx, self.intervall, self.on_neu = data_dir, ctx, intervall, on_neu
        self.stop_ev = threading.Event()
        self.thread = threading.Thread(target=self._lauf, daemon=True, name="zertifikat-waechter")

    def start(self):
        self.thread.start()
        return self

    def pruefen(self):
        """True, wenn neu ausgestellt wurde."""
        info = tls_dir(self.data_dir) / "server.json"
        namen, ips = standard_namen()
        namen = sorted(set(namen) | {MDNS_NAME})
        try:
            alt = json.loads(info.read_text("utf-8"))
        except (OSError, ValueError):
            alt = {}
        if alt.get("namen") == namen and alt.get("ips") == ips:
            return False
        crt, key = ensure_server_cert(self.data_dir, namen, ips)
        self.ctx.load_cert_chain(str(crt), str(key))
        if self.on_neu:
            self.on_neu(namen, ips)
        return True

    def _lauf(self):
        while not self.stop_ev.wait(self.intervall):
            try:
                self.pruefen()
            except Exception:
                pass

    def stop(self):
        self.stop_ev.set()


def ca_pem(data_dir):
    p = tls_dir(data_dir) / "ca.crt"
    if not p.exists():
        if not HAVE_CRYPTO:
            return None
        ensure_ca(data_dir)
    return p.read_bytes()


def ca_der(data_dir):
    pem = ca_pem(data_dir)
    if pem is None:
        return None
    return ssl.PEM_cert_to_DER_cert(pem.decode("ascii"))


def mobileconfig(data_dir):
    """iOS-Konfigurationsprofil (plist, unsigniert) mit der Firmen-CA."""
    der = ca_der(data_dir)
    if der is None:
        return None
    # Stabile UUIDs je CA, damit das Profil beim erneuten Laden ersetzt wird
    basis = uuid.uuid5(uuid.NAMESPACE_URL, "barlagepm-ca:" + der[-32:].hex())
    payload = {
        "PayloadCertificateFileName": "barlagepm-ca.cer", "PayloadContent": der,
        "PayloadDescription": "Firmen-Zertifikat für Barlage PM", "PayloadDisplayName": CA_NAME,
        "PayloadIdentifier": f"de.barlage.pm.ca.{basis}", "PayloadType": "com.apple.security.root",
        "PayloadUUID": str(uuid.uuid5(basis, "cert")).upper(), "PayloadVersion": 1,
    }
    profil = {
        "PayloadContent": [payload], "PayloadDescription": "Installiert das Firmen-Zertifikat, damit Barlage PM sicher (HTTPS) läuft.",
        "PayloadDisplayName": "Barlage PM Zertifikat", "PayloadIdentifier": f"de.barlage.pm.profil.{basis}",
        "PayloadOrganization": "Barlage PM", "PayloadRemovalDisallowed": False, "PayloadType": "Configuration",
        "PayloadUUID": str(uuid.uuid5(basis, "profil")).upper(), "PayloadVersion": 1,
    }
    return plistlib.dumps(profil, fmt=plistlib.FMT_XML)


def spezial(data_dir, path):
    """Liefert (status, body, mime, extra_headers) für /zertifikat* oder None."""
    if path in ("/zertifikat", "/zertifikat.crt", "/zertifikat.cer"):
        pem = ca_pem(data_dir)
        if pem is None:
            return 404, "Kein Zertifikat (HTTP-Modus)".encode(), "text/plain; charset=utf-8", {}
        if path == "/zertifikat.cer":
            return 200, ca_der(data_dir), "application/pkix-cert", {"Content-Disposition": 'attachment; filename="barlagepm-ca.cer"'}
        return 200, pem, "application/x-x509-ca-cert", {"Content-Disposition": 'attachment; filename="barlagepm-ca.crt"'}
    if path == "/zertifikat.mobileconfig":
        b = mobileconfig(data_dir)
        if b is None:
            return 404, "Kein Zertifikat (HTTP-Modus)".encode(), "text/plain; charset=utf-8", {}
        return 200, b, "application/x-apple-aspen-config", {"Content-Disposition": 'attachment; filename="barlagepm.mobileconfig"'}
    return None


def helfer_seite(host, https_port, data_dir=None):
    """Kleine Seite auf dem HTTP-Hilfsport: Zertifikat laden, dann zur HTTPS-App."""
    import html
    h = html.escape(host)
    ca = ca_name(data_dir) if data_dir else CA_NAME
    return f"""<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Barlage PM – Zertifikat</title><style>body{{font:16px system-ui,sans-serif;max-width:560px;margin:0 auto;padding:16px;background:#f6f7f8;color:#1d2125}}
a.b{{display:block;padding:14px;margin:10px 0;background:#032d6e;color:#fff;border-radius:10px;text-decoration:none;text-align:center}}
ol{{padding-left:20px}}li{{margin:6px 0}}</style></head><body><h1>Barlage PM einrichten</h1>
<p>Damit die App sicher (HTTPS) läuft, einmalig das Firmen-Zertifikat installieren.</p>
<h2>iPhone / iPad</h2><ol><li><a href="/zertifikat.mobileconfig">Profil laden</a> → „Zulassen“.</li>
<li>Einstellungen → „Profil geladen“ → Installieren.</li>
<li>Einstellungen → Allgemein → Info → Zertifikatsvertrauenseinstellungen → „{html.escape(ca)}“ aktivieren.</li></ol>
<a class="b" href="/zertifikat.mobileconfig">iOS-Profil laden</a>
<h2>Android / Windows</h2><a class="b" href="/zertifikat.crt">Zertifikat (ca.crt) laden</a>
<p>Android: Einstellungen → Sicherheit → Verschlüsselung → Zertifikat installieren → CA-Zertifikat.</p>
<p>Windows-PCs: Die Barlage-PM-App richtet das Zertifikat beim Start selbst ein (eine Rückfrage von Windows mit „Ja“ bestätigen).</p>
<a class="b" href="https://{h}:{https_port}/#/installieren">Weiter zur App (HTTPS)</a></body></html>""".encode("utf-8")
