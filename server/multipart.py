"""Eigener multipart/form-data-Parser (das cgi-Modul existiert ab Python 3.13 nicht mehr)."""
import re

from util import ApiError


def parse(content_type, body):
    """Gibt (fields: dict[str,str], files: dict[str,(filename, mime, bytes)]) zurück."""
    m = re.search(r'boundary=(?:"([^"]+)"|([^;]+))', content_type or "")
    if not m:
        raise ApiError(400, "Ungültige Anfrage: multipart-Grenze fehlt")
    boundary = ("--" + (m.group(1) or m.group(2)).strip()).encode("latin-1")
    fields, files = {}, {}
    for part in body.split(boundary)[1:]:
        if part.startswith(b"--"):
            break
        if part.startswith(b"\r\n"):
            part = part[2:]
        if part.endswith(b"\r\n"):
            part = part[:-2]
        head, sep, data = part.partition(b"\r\n\r\n")
        if not sep:
            continue
        headers = {}
        for line in head.decode("utf-8", "replace").split("\r\n"):
            k, _, v = line.partition(":")
            headers[k.strip().lower()] = v.strip()
        disp = headers.get("content-disposition", "")
        nm = re.search(r'(?<![a-z*])name="([^"]*)"', disp)
        fn = re.search(r'filename="([^"]*)"', disp)
        fn_star = re.search(r"filename\*=UTF-8''([^;]+)", disp, re.I)
        if not nm:
            continue
        name = nm.group(1)
        if fn or fn_star:
            from urllib.parse import unquote
            filename = unquote(fn_star.group(1)) if fn_star else fn.group(1)
            files[name] = (filename, headers.get("content-type", "application/octet-stream"), data)
        else:
            fields[name] = data.decode("utf-8", "replace")
    return fields, files
