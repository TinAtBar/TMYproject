"""Minimaler XLSX-Leser und -Schreiber (nur zipfile + xml)."""
import io
import re
import zipfile
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
RELNS = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def _col_index(ref):
    letters = re.match(r"[A-Z]+", ref).group(0)
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _oeffnen(data):
    try:
        return zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("Datei ist keine gültige .xlsx/.xlsm-Datei")


def _shared(z):
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        t_tag, rph = "{%s}t" % NS["m"], "{%s}rPh" % NS["m"]
        for si in root.findall("m:si", NS):
            teile = []
            for el in si:
                if el.tag == t_tag:
                    teile.append(el.text or "")
                elif el.tag != rph:  # Rich-Text-Runs <r><t>, Lautschrift <rPh> ignorieren
                    teile.extend(t.text or "" for t in el.iter(t_tag))
            shared.append("".join(teile))
    return shared


def blaetter(z):
    """Liste (name, pfad) in Reiter-Reihenfolge."""
    if isinstance(z, (bytes, bytearray)):
        z = _oeffnen(z)
    names = set(z.namelist())
    try:
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    except (KeyError, ET.ParseError):
        return [("Tabelle1", "xl/worksheets/sheet1.xml")] if "xl/worksheets/sheet1.xml" in names else []
    ziele = {}
    for rel in rels.findall(RELNS + "Relationship"):
        t = (rel.get("Target") or "")
        t = t.lstrip("/") if t.startswith("/") else "xl/" + t
        ziele[rel.get("Id")] = re.sub(r"[^/]+/\.\./", "", t)
    out = []
    for sh in wb.findall("m:sheets/m:sheet", NS):
        pfad = ziele.get(sh.get("{%s}id" % NS["r"]))
        if pfad in names:
            out.append((sh.get("name"), pfad))
    return out


def _blatt_lesen(z, pfad, shared, max_zeilen=None, max_spalten=None):
    root = ET.fromstring(z.read(pfad))
    m = "{%s}" % NS["m"]
    rows = []
    for row in root.iter(m + "row"):
        rnr = row.get("r")
        if rnr and rnr.isdigit():
            rnr = int(rnr)
            if max_zeilen and rnr > max_zeilen:
                break
            while len(rows) < rnr - 1:  # Lücken auffüllen → rows[i] = Zeile i+1
                rows.append([])
        vals = {}
        for c in row.findall(m + "c"):
            ref, t = c.get("r"), c.get("t")
            idx = _col_index(ref) if ref else len(vals)
            if max_spalten and idx >= max_spalten:
                continue
            v = c.find(m + "v")
            if t == "s" and v is not None:
                val = shared[int(v.text)]
            elif t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter(m + "t"))
            elif v is not None and v.text is not None:
                val = v.text
                if t not in ("str", "e", "b"):
                    try:
                        f = float(val)
                        val = int(f) if f.is_integer() else f
                    except ValueError:
                        pass
            else:
                val = None
            vals[idx] = val
        if vals:
            line = [None] * (max(vals) + 1)
            for i, v in vals.items():
                line[i] = v
            rows.append(line)
        else:
            rows.append([])
    return rows


def mappe(data, nur=None, max_zeilen=None, max_spalten=None):
    """Liest mehrere Blätter (zwischengespeicherte Werte, auch .xlsm).
    nur: optionale Menge/Funktion von Blattnamen. Rückgabe: {name: rows} in Reiter-Reihenfolge."""
    z = _oeffnen(data)
    shared = _shared(z)
    out = {}
    for name, pfad in blaetter(z):
        if nur is not None and not (nur(name) if callable(nur) else name in nur):
            continue
        out[name] = _blatt_lesen(z, pfad, shared, max_zeilen, max_spalten)
    return out


def lesen(data):
    """Liest das erste Tabellenblatt. Rückgabe: Liste von Zeilen (Listen von Strings/Zahlen)."""
    z = _oeffnen(data)
    bl = blaetter(z)
    if not bl:
        raise ValueError("Kein Tabellenblatt in der Datei gefunden")
    return _blatt_lesen(z, bl[0][1], _shared(z))


def _colname(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def schreiben(header, rows, blattname="OPL", rot=None):
    """Erzeugt eine .xlsx (Bytes) mit Inline-Strings; erste Zeile fett.

    R3-B: rot = Menge von (zeile, spalte) (0-basiert, ohne Kopfzeile) → rote Schrift.
    """
    rot = rot or set()
    def cell(ref, v, style):
        st = f' s="{style}"' if style else ""
        if v is None or v == "":
            return ""
        if isinstance(v, bool):
            v = "ja" if v else "nein"
        if isinstance(v, (int, float)):
            return f'<c r="{ref}"{st}><v>{v}</v></c>'
        txt = escape(str(v)).replace("\r", "")
        txt = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", txt)
        return f'<c r="{ref}" t="inlineStr"{st}><is><t xml:space="preserve">{txt}</t></is></c>'

    lines = []
    for ri, r in enumerate([header] + list(rows)):
        cells = "".join(cell(f"{_colname(ci)}{ri + 1}", v, 1 if ri == 0 else (2 if (ri - 1, ci) in rot else 0)) for ci, v in enumerate(r))
        lines.append(f'<row r="{ri + 1}">{cells}</row>')
    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             f'<worksheet xmlns="{NS["m"]}"><sheetViews><sheetView workbookViewId="0">'
             '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
             f'<sheetData>{"".join(lines)}</sheetData>'
             f'<autoFilter ref="A1:{_colname(max(len(header), 1) - 1)}{len(rows) + 1}"/></worksheet>')
    files = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '</Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>',
        "xl/workbook.xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<workbook xmlns="{NS["m"]}" xmlns:r="{NS["r"]}"><sheets>'
        f'<sheet name="{escape(blattname[:31])}" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        '</Relationships>',
        "xl/styles.xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<styleSheet xmlns="{NS["m"]}"><fonts count="3"><font><sz val="11"/><name val="Calibri"/></font>'
        '<font><b/><sz val="11"/><name val="Calibri"/></font><font><color rgb="FFC00000"/><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
        '<borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs>'
        '<cellXfs count="3"><xf fontId="0"/><xf fontId="1" applyFont="1"/><xf fontId="2" applyFont="1"/></cellXfs></styleSheet>',
        "xl/worksheets/sheet1.xml": sheet,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, c in files.items():
            z.writestr(n, c)
    return buf.getvalue()


# ------------------------------------------------------------------ R5-F: Mappe mit mehreren Blättern + Formaten
def _serial(iso):
    import datetime as _dt
    try:
        d = _dt.date.fromisoformat(str(iso)[:10])
    except ValueError:
        return None
    return (d - _dt.date(1899, 12, 30)).days


QUOT = {'"': "&quot;"}


def mappe_schreiben(blaetter):
    """R5-F: blaetter = [{name, rows:[[zelle]], breiten:[zeichen], }] → .xlsx-Bytes.

    Zelle: Wert oder dict {v, fett, rot, umbruch, datum (ISO → Excel-Datum TT.MM.JJJJ), gross}.
    Blattnamen werden auf 31 Zeichen gekürzt; verbotene Zeichen \\ / ? * [ ] : entfernt.
    """
    fonts, xfs = [], []

    def font_id(fett, rot, gross):
        key = (fett, rot, gross)
        if key not in fonts:
            fonts.append(key)
        return fonts.index(key)

    def style(z):
        key = (font_id(bool(z.get("fett")), bool(z.get("rot")), bool(z.get("gross"))), bool(z.get("umbruch")), bool(z.get("datum")))
        if key not in xfs:
            xfs.append(key)
        return xfs.index(key)
    font_id(False, False, False)
    xfs.append((0, False, False))

    def cell(ref, z):
        if not isinstance(z, dict):
            z = {"v": z}
        v = z.get("v")
        if v is None or v == "":
            return ""
        if z.get("datum"):
            sv = _serial(v)
            if sv is None:
                z = {**z, "datum": False}
            else:
                v = sv
        s = style(z)
        st = f' s="{s}"' if s else ""
        if isinstance(v, bool):
            v = "ja" if v else "nein"
        if isinstance(v, (int, float)):
            return f'<c r="{ref}"{st}><v>{v}</v></c>'
        txt = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", escape(str(v)).replace("\r", ""))
        return f'<c r="{ref}" t="inlineStr"{st}><is><t xml:space="preserve">{txt}</t></is></c>'

    namen, sheets = [], []
    for i, b in enumerate(blaetter):
        n = re.sub(r"[\\/?*\[\]:]", "-", str(b.get("name") or f"Tabelle{i + 1}"))[:31] or f"Tabelle{i + 1}"
        basis, k = n, 2
        while n.lower() in (x.lower() for x in namen):
            n = f"{basis[:28]}~{k}"; k += 1
        namen.append(n)
        lines = []
        for ri, r in enumerate(b.get("rows") or []):
            cells = "".join(cell(f"{_colname(ci)}{ri + 1}", z) for ci, z in enumerate(r))
            lines.append(f'<row r="{ri + 1}">{cells}</row>')
        cols = ""
        if b.get("breiten"):
            cols = "<cols>" + "".join(f'<col min="{j + 1}" max="{j + 1}" width="{w}" customWidth="1"/>' for j, w in enumerate(b["breiten"])) + "</cols>"
        sheets.append('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                      f'<worksheet xmlns="{NS["m"]}">{cols}<sheetData>{"".join(lines)}</sheetData>'
                      '<pageMargins left="0.5" right="0.5" top="0.6" bottom="0.6" header="0.3" footer="0.3"/>'
                      '<pageSetup paperSize="9" orientation="landscape" fitToHeight="0"/></worksheet>')
    rot_xml, wrap_xml, num_xml = '<color rgb="FFFF0000"/>', ' applyAlignment="1"><alignment wrapText="1" vertical="top"/></xf>', ' applyNumberFormat="1"'
    font_xml = "".join(f'<font>{"<b/>" if f else ""}{rot_xml if r else ""}<sz val="{14 if g else 11}"/><name val="Arial"/></font>'
                       for f, r, g in fonts)
    xf_xml = "".join(f'<xf numFmtId="{164 if d else 0}" fontId="{fi}" fillId="0" borderId="0" xfId="0" applyFont="1"'
                     f'{num_xml if d else ""}{wrap_xml if u else "/>"}'
                     for fi, u, d in xfs)
    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              f'<styleSheet xmlns="{NS["m"]}"><numFmts count="1"><numFmt numFmtId="164" formatCode="dd.mm.yyyy"/></numFmts>'
              f'<fonts count="{len(fonts)}">{font_xml}</fonts>'
              '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
              '<borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs>'
              f'<cellXfs count="{len(xfs)}">{xf_xml}</cellXfs></styleSheet>')
    ct = "".join(f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                 for i in range(len(sheets)))
    files = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        f'{ct}<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>',
        "xl/workbook.xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<workbook xmlns="{NS["m"]}" xmlns:r="{NS["r"]}"><sheets>'
        + "".join(f'<sheet name="{escape(n, QUOT)}" sheetId="{i + 1}" r:id="rId{i + 1}"/>' for i, n in enumerate(namen))
        + '</sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(f'<Relationship Id="rId{i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i + 1}.xml"/>'
                  for i in range(len(sheets)))
        + f'<Relationship Id="rId{len(sheets) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        '</Relationships>',
        "xl/styles.xml": styles,
    }
    for i, s in enumerate(sheets):
        files[f"xl/worksheets/sheet{i + 1}.xml"] = s
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, c in files.items():
            z.writestr(n, c)
    return buf.getvalue()
