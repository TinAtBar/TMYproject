"""mobile: Minimaler mDNS-Responder (nur Standardbibliothek) – kündigt opl.local → LAN-IP an.

- beantwortet A-Anfragen (auch ANY) für den Namen, unicast-Antwort wenn QU-Bit gesetzt oder Quellport ≠ 5353
- Probing light: vor dem Start 3 Anfragen; antwortet jemand anderes mit anderer IP → Warnung im Log (Konflikt)
- Goodbye (TTL 0) beim Stoppen
- Port 5353 belegt/kein Multicast → Log-Hinweis, Server läuft weiter
"""
import socket
import struct
import threading
import time

MCAST = "224.0.0.251"
PORT = 5353
TTL = 120


def encode_name(name):
    out = b""
    for part in name.rstrip(".").split("."):
        b = part.encode("utf-8")
        out += bytes([len(b)]) + b
    return out + b"\x00"


def decode_name(data, off):
    labels, jumped, end = [], False, None
    for _ in range(128):
        n = data[off]
        if n == 0:
            off += 1
            break
        if n & 0xC0 == 0xC0:
            ptr = ((n & 0x3F) << 8) | data[off + 1]
            if not jumped:
                end = off + 2
            jumped, off = True, ptr
            continue
        labels.append(data[off + 1:off + 1 + n].decode("utf-8", "replace"))
        off += 1 + n
    return ".".join(labels), (end if jumped else off)


def parse_questions(data):
    """Gibt (id, flags, [(name, qtype, qclass)], answers[(name,type,rdata)]) zurück."""
    tid, flags, qd, an, ns, ar = struct.unpack("!HHHHHH", data[:12])
    off, qs, ans = 12, [], []
    for _ in range(qd):
        name, off = decode_name(data, off)
        qt, qc = struct.unpack("!HH", data[off:off + 4])
        off += 4
        qs.append((name.lower(), qt, qc))
    for _ in range(an):
        name, off = decode_name(data, off)
        t, c, ttl, ln = struct.unpack("!HHIH", data[off:off + 10])
        off += 10
        ans.append((name.lower(), t, data[off:off + ln]))
        off += ln
    return tid, flags, qs, ans


def build_answer(name, ip, ttl=TTL, tid=0):
    hdr = struct.pack("!HHHHHH", tid, 0x8400, 0, 1, 0, 0)
    rr = encode_name(name) + struct.pack("!HHIH", 1, 0x8001, ttl, 4) + socket.inet_aton(ip)
    return hdr + rr


def build_query(name, qtype=1, unicast=False):
    hdr = struct.pack("!HHHHHH", 0, 0, 1, 0, 0, 0)
    return hdr + encode_name(name) + struct.pack("!HH", qtype, 0x8001 if unicast else 1)


class Responder:
    def __init__(self, name="opl.local", ip=None, port=PORT, bind="0.0.0.0", multicast=True, log=print):
        self.name, self.ip, self.port, self.bind, self.multicast, self.log = name.lower(), ip, port, bind, multicast, log
        self.sock = None
        self._stop = threading.Event()
        self._thread = None
        self.konflikt = False

    def start(self):
        s = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT"):
                try:
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                except OSError:
                    pass
            s.bind((self.bind, self.port))
            if self.multicast:
                try:
                    mreq = socket.inet_aton(MCAST) + socket.inet_aton(self.ip if self.ip and not self.ip.startswith("127.") else "0.0.0.0")
                    s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
                    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
                    if self.ip and not self.ip.startswith("127."):
                        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(self.ip))
                except OSError as e:
                    self.log(f"mDNS: Multicast nicht verfügbar ({e}) – {self.name} wird nicht angekündigt")
            s.settimeout(0.5)
            self.sock = s
        except OSError as e:
            if s:
                s.close()
            self.log(f"mDNS: Port {self.port} nicht nutzbar ({e}) – {self.name} wird nicht angekündigt, Zugriff per IP")
            return False
        self._thread = threading.Thread(target=self._loop, daemon=True, name="mdns")
        self._thread.start()
        if self.multicast:
            threading.Thread(target=self._probe_announce, daemon=True).start()
        return True

    def _send_mcast(self, pkt):
        try:
            self.sock.sendto(pkt, (MCAST, PORT))
        except OSError:
            pass

    def _probe_announce(self):
        for _ in range(3):
            if self._stop.is_set():
                return
            self._send_mcast(build_query(self.name, 255, unicast=True))
            time.sleep(0.25)
        if self.konflikt:
            self.log(f"mDNS: Konflikt – ein anderes Gerät meldet {self.name}. Handys bitte per IP verbinden.")
        for _ in range(2):
            self._send_mcast(build_answer(self.name, self.ip))
            time.sleep(1)

    def _loop(self):
        while not self._stop.is_set():
            try:
                data, addr = self.sock.recvfrom(9000)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                self.handle(data, addr)
            except Exception:  # noqa: BLE001 – kaputte Pakete ignorieren
                pass

    def handle(self, data, addr):
        tid, flags, qs, ans = parse_questions(data)
        if flags & 0x8000:  # Antwort eines anderen
            for name, t, rd in ans:
                if name == self.name and t == 1 and len(rd) == 4 and socket.inet_ntoa(rd) != self.ip:
                    self.konflikt = True
            return
        for name, qt, qc in qs:
            if name == self.name and qt in (1, 255):
                pkt = build_answer(self.name, self.ip, tid=tid if addr[1] != PORT else 0)
                if (qc & 0x8000) or addr[1] != PORT or not self.multicast:
                    self.sock.sendto(pkt, addr)
                else:
                    self._send_mcast(pkt)
                return

    def stop(self):
        if not self.sock:
            return
        if self.multicast:
            self._send_mcast(build_answer(self.name, self.ip, ttl=0))  # Goodbye
        self._stop.set()
        if self._thread:
            self._thread.join(2)
        try:
            self.sock.close()
        except OSError:
            pass
        self.sock = None
