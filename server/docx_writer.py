"""Minimaler .docx-Schreiber (WordprocessingML per zipfile, ohne Fremdpakete).

Bausteine: Überschrift, Absatz, Aufzählung mit Ebenen (numbering.xml), Tabelle (mit Kopfzeile/Rahmen).
    d = Docx(); d.heading("Titel", 1); d.para("Text"); d.bullet("Punkt", ebene=1)
    d.table([["Nr.", "Thema", "Zuständig"], ...], widths=[900, 6500, 2000], header=True)
    data = d.bytes()
"""
import io
import zipfile
from xml.sax.saxutils import escape

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" ' \
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
</Types>"""

RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
</Relationships>"""

DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>
</Relationships>"""

STYLES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles {W}>
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial" w:eastAsia="Arial"/><w:sz w:val="20"/><w:szCs w:val="20"/><w:lang w:val="de-DE"/></w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="60" w:line="259" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Standard"><w:name w:val="Normal"/></w:style>
<w:style w:type="paragraph" w:styleId="berschrift1"><w:name w:val="heading 1"/><w:basedOn w:val="Standard"/><w:next w:val="Standard"/><w:pPr><w:keepNext/><w:spacing w:before="240" w:after="120"/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:sz w:val="28"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="berschrift2"><w:name w:val="heading 2"/><w:basedOn w:val="Standard"/><w:next w:val="Standard"/><w:pPr><w:keepNext/><w:spacing w:before="180" w:after="80"/><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:b/><w:sz w:val="24"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Listenabsatz"><w:name w:val="List Paragraph"/><w:basedOn w:val="Standard"/><w:pPr><w:spacing w:after="0"/></w:pPr></w:style>
<w:style w:type="table" w:styleId="Tabellenraster"><w:name w:val="Table Grid"/><w:tblPr><w:tblBorders>
<w:top w:val="single" w:sz="4" w:space="0" w:color="808080"/><w:left w:val="single" w:sz="4" w:space="0" w:color="808080"/>
<w:bottom w:val="single" w:sz="4" w:space="0" w:color="808080"/><w:right w:val="single" w:sz="4" w:space="0" w:color="808080"/>
<w:insideH w:val="single" w:sz="4" w:space="0" w:color="808080"/><w:insideV w:val="single" w:sz="4" w:space="0" w:color="808080"/>
</w:tblBorders><w:tblCellMar><w:left w:w="80" w:type="dxa"/><w:right w:w="80" w:type="dxa"/></w:tblCellMar></w:tblPr></w:style>
</w:styles>"""


def _numbering():
    sym = ["•", "o", "▪"] * 3
    fonts = ["Symbol", "Courier New", "Wingdings"] * 3
    lvls = []
    for i in range(9):
        ch = "·" if sym[i] == "•" else ("§" if sym[i] == "▪" else "o")
        lvls.append(f'<w:lvl w:ilvl="{i}"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="{ch}"/>'
                    f'<w:lvlJc w:val="left"/><w:pPr><w:ind w:left="{360 + 360 * i}" w:hanging="360"/></w:pPr>'
                    f'<w:rPr><w:rFonts w:ascii="{fonts[i]}" w:hAnsi="{fonts[i]}" w:hint="default"/></w:rPr></w:lvl>')
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:numbering {W}>'
            f'<w:abstractNum w:abstractNumId="0"><w:multiLevelType w:val="hybridMultilevel"/>{"".join(lvls)}</w:abstractNum>'
            f'<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num></w:numbering>')


def _run(text, bold=False, strike=False, color=None, size=None):
    rpr = ""
    if bold or strike or color or size:
        rpr = "<w:rPr>" + ("<w:b/>" if bold else "") + ("<w:strike/>" if strike else "") + \
              (f'<w:color w:val="{color}"/>' if color else "") + (f'<w:sz w:val="{size}"/>' if size else "") + "</w:rPr>"
    parts = str(text or "").split("\n")
    inner = '<w:br/>'.join(f'<w:t xml:space="preserve">{escape(p)}</w:t>' for p in parts)
    return f"<w:r>{rpr}{inner}</w:r>"


def _p(runs, style=None, num_level=None, align=None, keep=False):
    ppr = ""
    if style or num_level is not None or align or keep:
        ppr = "<w:pPr>" + (f'<w:pStyle w:val="{style}"/>' if style else "") + ("<w:keepNext/>" if keep else "") + \
              (f'<w:numPr><w:ilvl w:val="{num_level}"/><w:numId w:val="1"/></w:numPr>' if num_level is not None else "") + \
              (f'<w:jc w:val="{align}"/>' if align else "") + "</w:pPr>"
    return f"<w:p>{ppr}{runs}</w:p>"


class Docx:
    def __init__(self, titel=""):
        self.body = []
        self.titel = titel

    def heading(self, text, level=1):
        self.body.append(_p(_run(text), style=f"berschrift{min(max(level, 1), 2)}"))

    def para(self, text, bold=False, size=None):
        self.body.append(_p(_run(text, bold=bold, size=size)))

    def bullet(self, text, ebene=0, erledigt=False):
        self.body.append(_p(_run(text) + (_run("  erledigt", color="2E7D32", bold=True) if erledigt else ""),
                            style="Listenabsatz", num_level=min(max(int(ebene), 0), 8)))

    def table(self, rows, widths=None, header=False, shade_first_col=False):
        """rows: Liste von Zeilen; Zelle = str | {"text":…, "bold":…, "bullets":[(text, ebene, erledigt)], "span":n}."""
        n = max((sum((c.get("span", 1) if isinstance(c, dict) else 1) for c in r) for r in rows), default=1)
        widths = widths or [int(9600 / n)] * n
        grid = "".join(f'<w:gridCol w:w="{w}"/>' for w in widths)
        out = [f'<w:tbl><w:tblPr><w:tblStyle w:val="Tabellenraster"/><w:tblW w:w="{sum(widths)}" w:type="dxa"/>'
               f'<w:tblLayout w:type="fixed"/></w:tblPr><w:tblGrid>{grid}</w:tblGrid>']
        for ri, r in enumerate(rows):
            out.append("<w:tr>" + ('<w:trPr><w:tblHeader/></w:trPr>' if header and ri == 0 else ""))
            ci = 0
            for c in r:
                c = c if isinstance(c, dict) else {"text": c}
                span = c.get("span", 1)
                w = sum(widths[ci:ci + span])
                shade = (header and ri == 0) or (shade_first_col and ci % 2 == 0 and not c.get("noshade")) or c.get("shade")
                tcpr = f'<w:tcPr><w:tcW w:w="{w}" w:type="dxa"/>' + (f'<w:gridSpan w:val="{span}"/>' if span > 1 else "") + \
                       ('<w:shd w:val="clear" w:color="auto" w:fill="E7ECF2"/>' if shade else "") + "</w:tcPr>"
                paras = []
                if c.get("text") not in (None, "") or not c.get("bullets"):
                    paras.append(_p(_run(c.get("text", ""), bold=c.get("bold") or (header and ri == 0))))
                for t, lvl, erl in c.get("bullets") or []:
                    paras.append(_p(_run(t) + (_run("  erledigt", color="2E7D32", bold=True) if erl else ""),
                                    style="Listenabsatz", num_level=min(max(int(lvl), 0), 8)))
                out.append(f"<w:tc>{tcpr}{''.join(paras)}</w:tc>")
                ci += span
            out.append("</w:tr>")
        out.append("</w:tbl>")
        self.body.append("".join(out))
        self.body.append(_p(""))

    def document_xml(self):
        sect = ('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1134" w:bottom="1134" '
                'w:left="1134" w:header="567" w:footer="567" w:gutter="0"/></w:sectPr>')
        return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:document {W}><w:body>'
                + "".join(self.body) + sect + "</w:body></w:document>")

    def bytes(self):
        core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<cp:coreProperties '
                'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>' + escape(self.titel) +
                '</dc:title><dc:creator>Barlage PM</dc:creator></cp:coreProperties>')
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", CONTENT_TYPES)
            z.writestr("_rels/.rels", RELS)
            z.writestr("docProps/core.xml", core)
            z.writestr("word/_rels/document.xml.rels", DOC_RELS)
            z.writestr("word/styles.xml", STYLES)
            z.writestr("word/numbering.xml", _numbering())
            z.writestr("word/document.xml", self.document_xml())
        return buf.getvalue()


# ------------------------------------------------------------------ Lesen (für „Aus Word einfügen“)
NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def lesen(data):
    """Liest eine .docx in eine Blockliste: ("p", text, ebene|None) und ("table", [[zelltext, …], …]).

    Zelltexte enthalten Absätze getrennt durch \\n; Aufzählungen in Zellen werden als „\\t“*ebene + „• “ markiert.
    """
    import xml.etree.ElementTree as ET
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    body = root.find(NS + "body")

    def ptext(p):
        t = []
        for el in p.iter():
            if el.tag == NS + "t" and el.text:
                t.append(el.text)
            elif el.tag in (NS + "tab",):
                t.append("\t")
            elif el.tag in (NS + "br", NS + "cr"):
                t.append("\n")
        return "".join(t)

    def plevel(p):
        ppr = p.find(NS + "pPr")
        if ppr is None:
            return None
        num = ppr.find(NS + "numPr")
        if num is None:
            return None
        il = num.find(NS + "ilvl")
        return int(il.get(NS + "val", "0")) if il is not None else 0

    blocks = []
    for el in body:
        if el.tag == NS + "p":
            blocks.append(("p", ptext(el), plevel(el)))
        elif el.tag == NS + "tbl":
            rows = []
            for tr in el.iter(NS + "tr"):
                cells = []
                for tc in tr.findall(NS + "tc"):
                    lines = []
                    for p in tc.iter(NS + "p"):
                        lv = plevel(p)
                        tx = ptext(p)
                        if lv is not None and tx.strip():
                            lines.append("\t" * lv + "• " + tx)
                        else:
                            lines.append(tx)
                    cells.append("\n".join(lines).strip("\n"))
                rows.append(cells)
            blocks.append(("table", rows))
    return blocks
