"""Render an e-filed return to page images with the IRS's own MeF display stylesheets.

Pipeline: catalog XML -> one XSLT 1.0 transform per return document (main form, each
schedule, each attached statement) with the official stylesheet for the return's tax
year, in the "separated" print mode TEOS images use -> headless Chromium prints each
document at 100% scale on Letter-width sheets (landscape where the IRS PrintMode.xml says
so; sheet height stretched up to MAX_STRETCH so a whole IRS form page fits) -> pages merged
into one PDF, blank sheets dropped -> one grayscale PNG per page.

The page header reproduces TEOS images: "efile GRAPHIC print - DO NOT PROCESS |
As Filed Data - | DLN: ..." (DLN from the IRS index CSV when present, else the EIN).
See docs/rendering.md.

    uv run python -m bench990.render <object_id> [out_dir]
"""

from __future__ import annotations

import copy
import json
import logging
import math
import mmap
import re
import shutil
import sys
import time
import zipfile
from functools import lru_cache
from pathlib import Path

import httpx
import pypdfium2 as pdfium
from lxml import etree
from playwright.sync_api import Route, sync_playwright

from bench990 import corpus

log = logging.getLogger(__name__)

STYLESHEETS = corpus.ROOT / "data" / "stylesheets"
PACKAGE_URL = "https://www.irs.gov/pub/irs-schema/{}.zip"
# Tax year -> newest IRS stylesheet package (https://www.irs.gov/e-file-providers/modernized-e-file-mef-stylesheets)
# that ships both Stylesheets/<year>/ and the matching rrprd/sdi/versioned/<year>/ assets.
PACKAGES = {
    2019: "py2022r1",
    2020: "py2023r1",
    2021: "py2023r1",
    2022: "py2024r1",
    2023: "py2024r1",
    2024: "py2025r1",
    2025: "py2026r1",
    2026: "py2027r5",
}
HOST = "http://irs.local"  # Chromium loads pages here; the stylesheets use absolute /mef/... asset paths
PRINT_MODE = "separated"
DPI = 150
MARGIN_IN = 0.3
LETTER_IN = (8.5, 11.0)
CSS_PX_PER_IN = 96
# IRS form pages (content between forced page breaks) are laid out for IE and can run past a
# Letter sheet (Form 990 Part VIII is ~13 in). Like TEOS images, which are cropped to each page,
# we keep 100% scale and stretch a document's sheet height to its tallest form page, up to this
# factor; anything taller (long statements, additional-data tables) flows across sheets.
MAX_STRETCH = 1.3
SLACK_PX = 16
# Forced breaks -> heights (CSS px) of the runs between them, plus the widest right edge.
FIT_JS = """() => {
  const cuts = [0, document.documentElement.scrollHeight];
  let wide = 0;
  for (const e of document.body.querySelectorAll('*')) {
    const r = e.getBoundingClientRect(), s = getComputedStyle(e);
    wide = Math.max(wide, r.right);
    if (s.breakBefore === 'page') cuts.push(r.top + scrollY);
    if (s.breakAfter === 'page') cuts.push(r.bottom + scrollY);
  }
  cuts.sort((a, b) => a - b);
  const runs = [];
  for (let i = 1; i < cuts.length; i++) runs.push(cuts[i] - cuts[i - 1]);
  return [runs, wide];
}"""
PRINT_CSS = (
    # The stylesheets target Internet Explorer, which ignores page breaks on table rows; Chromium
    # honours them and then emits blank sheets where a row break meets the next block's break.
    "tr { page-break-after: auto !important; break-after: auto !important; }"
    # The borrowed screen CSS lacks its print-mode branch, which hides "Return to Form" buttons.
    ".styLeftOverButtonContainer, .styLeftOverButtonContainerLandscape { visibility: hidden; }"
    # Additional-data table headers are white-on-<user preference colour> on screen; TEOS prints black.
    ".styDepTblHdr { color: black; background-color: transparent; }"
)
# Images referenced by the TY2022-2024 IRS990.xsl but absent from every published package.
# Two have same-label siblings; the third is drawn as the label TEOS images show.
IMAGE_SUBSTITUTES = {
    "990_Institutional_Trustee_update.gif": "990_Institutional_Trustee.gif",
    "990_CGGOSA.gif": "990_CGGOSAmt.gif",
}
MISC_REVENUE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="30" height="112">'
    '<g transform="translate(13,110) rotate(-90)" font-family="Arial,sans-serif" font-size="10" font-weight="bold">'
    '<text x="0" y="0">Miscellaneous</text><text x="22" y="12">Revenue</text></g></svg>'
)

APPDATA = """<AppData>
  <ApplicationProperties>
    <FormHeaderGeneric>efile GRAPHIC print - DO NOT PROCESS</FormHeaderGeneric>
    <FormHeaderOriginalData>As Filed Data</FormHeaderOriginalData>
    <SystemMode/>
  </ApplicationProperties>
  <UserPreferences/>
  <Parameters>
    <Stage>original</Stage>
    <DLN/><DLNLatest/><TIN/>
    <TaxpayerPrint>false</TaxpayerPrint>
    <Print/>
    <DocumentId/>
    <ReturnVersion/>
    <SubmissionVersion/>
    <TaxYear/>
    <SubmissionType/>
    <Location>RET</Location>
    <LocationSeq>1</LocationSeq>
  </Parameters>
  <SubmissionHeaderAndDocument>
    <SubmissionDocument/>
  </SubmissionHeaderAndDocument>
</AppData>"""


def stylesheet_root(year: int) -> Path:
    """Directory holding mef/Stylesheets/<year>/ and mef/rrprd/ for a tax year; downloads on first use."""
    root = STYLESHEETS / str(year)
    if (root / "mef" / "Stylesheets" / str(year)).is_dir():
        return root
    package = PACKAGES[year]
    archive = STYLESHEETS / f"{package}.zip"
    if not archive.exists():
        STYLESHEETS.mkdir(parents=True, exist_ok=True)
        part = archive.with_suffix(".zip.part")
        with httpx.stream("GET", PACKAGE_URL.format(package), follow_redirects=True, timeout=120) as r:
            r.raise_for_status()
            with part.open("wb") as fh:
                for chunk in r.iter_bytes(1 << 20):
                    fh.write(chunk)
        part.rename(archive)
    keep = (f"mef/Stylesheets/{year}/", "mef/rrprd/sdi/versioned/", "mef/rrprd/common/")
    staging = STYLESHEETS / f".{year}.partial"
    shutil.rmtree(staging, ignore_errors=True)
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            # Packages nest the tree under a release folder (PY2024R11/mef/...) or start at mef/.
            at = info.filename.find("mef/")
            rel = info.filename[at:] if at >= 0 else ""
            if info.is_dir() or not rel.startswith(keep):
                continue
            dest = staging / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(zf.read(info))
    staging.rename(root)
    return root


PAPER_RETURN_PARAM = '<xsl:param name="PaperReturnIndicator" select="/AppData/Parameters/PaperReturnIndicator"/>'
SET_INITIAL_STATE_ATTR = re.compile(
    r'(<xsl:template name="SetInitialState">.*?)<xsl:attribute name="style">[^<]*</xsl:attribute>(.*?</xsl:template>)', re.S
)
# What SetInitialState would have set on print-mode table containers.
LENIENT_PRINT_CSS = (
    ".styTableContainer, .styTableContainerNBB, .styTableContainerLandscape, .styTableContainerLandscapeNBB"
    " { overflow: visible !important; height: auto !important; display: block !important; }"
)


class _Compat(etree.Resolver):
    """Load-time fixes for stylesheet errors that MSXML tolerates and libxslt rejects."""

    def __init__(self, lenient_print: bool) -> None:
        super().__init__()
        self.lenient_print = lenient_print

    def resolve(self, url: str, pubid: str | None, context: object) -> object | None:
        path = Path(url.removeprefix("file://"))
        if path.name == "CommonPathRef.xsl":
            text = path.read_text(encoding="utf-8")
            # TY2019-2021 AddHeader.xsl reads $PaperReturnIndicator, declared only from TY2022 on.
            if 'name="PaperReturnIndicator"' not in text:
                text = text.replace("</xsl:stylesheet>", PAPER_RETURN_PARAM + "</xsl:stylesheet>")
                return self.resolve_string(text, context, base_url=url)
        if path.name == "PopulateTemplate.xsl" and self.lenient_print:
            # Some forms call SetInitialState after writing children; MSXML drops the late
            # attribute, libxslt aborts. Drop it and apply its style via LENIENT_PRINT_CSS.
            text = SET_INITIAL_STATE_ATTR.sub(r"\1\2", path.read_text(encoding="utf-8"))
            return self.resolve_string(text, context, base_url=url)
        return None


@lru_cache(maxsize=256)
def _xslt(path: Path, lenient_print: bool = False) -> etree.XSLT:
    if not path.is_file():
        raise FileNotFoundError(f"no IRS stylesheet for document {path.stem} in {path.parent}")
    parser = etree.XMLParser()
    parser.resolvers.add(_Compat(lenient_print))
    return etree.XSLT(etree.parse(str(path), parser))


def _transform(xsl: Path, app: etree._Element) -> str:
    """One return document -> standalone print-mode HTML."""
    try:
        return _print_html(_xslt(xsl), app)
    except etree.XSLTApplyError as e:
        if "Cannot add attributes" not in str(e):
            raise
        return _print_html(_xslt(xsl, lenient_print=True), app, LENIENT_PRINT_CSS)


def _print_html(xslt: etree.XSLT, app: etree._Element, extra_css: str = "") -> str:
    # Print mode "separated" is what TEOS images use: repeating groups that overflow the form
    # lines move to "Additional Data" tables instead of collapsed scroll boxes. The stylesheets
    # only emit the form's own CSS in screen mode, so borrow it from a screen-mode transform.
    app.find("Parameters/Print").text = ""
    screen = xslt(app).getroot()
    app.find("Parameters/Print").text = PRINT_MODE
    printed = xslt(app).getroot()
    head = printed.find("head")
    for style in screen.iterfind("head/style"):
        head.append(style)
    etree.SubElement(head, "style").text = PRINT_CSS + extra_css
    # ASCII with character references: the stylesheets declare ISO-8859-1 in a meta tag.
    return "<!DOCTYPE html>\n" + etree.tostring(printed, method="html", encoding="ascii").decode()


@lru_cache(maxsize=16)
def _landscape(year: int) -> frozenset[str]:
    doc = etree.parse(str(stylesheet_root(year) / "mef" / "Stylesheets" / str(year) / "PrintMode.xml"))
    return frozenset(doc.xpath("/PrintMode/Landscape/Document/@documentName"))


def dln(filing: corpus.Filing) -> str | None:
    """DLN for a filing from the IRS index CSV of its batch year, if downloaded."""
    index = corpus.RAW / f"index_{filing.batch[:4]}.csv"
    if not index.exists():
        return None
    with index.open("rb") as fh, mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as mm:
        at = mm.find(f",{filing.object_id},".encode())
        if at < 0:
            return None
        start = mm.rfind(b"\n", 0, at) + 1
        line = mm[start : mm.find(b"\n", at)].decode()
    # RETURN_ID,FILING_TYPE,EIN,TAX_PERIOD,SUB_DATE,TAXPAYER_NAME,RETURN_TYPE,DLN,OBJECT_ID,XML_BATCH_ID;
    # names may contain commas, so index from the right.
    return line.rstrip("\r").split(",")[-3] or None


def _strip_namespaces(root: etree._Element) -> etree._Element:
    """The IRS stylesheets select unqualified names (IRS990/...), so drop the efile namespace."""
    for el in root.iter():
        if isinstance(el.tag, str):
            el.tag = etree.QName(el).localname
    etree.cleanup_namespaces(root)
    return root


def documents(object_id: str) -> list[tuple[str, str, bool]]:
    """(document name, HTML, landscape) for every document in the return, in filing order."""
    filing = corpus.get(object_id)
    if filing is None:
        raise KeyError(object_id)
    ret = _strip_namespaces(corpus.load_xml(filing.batch, object_id))
    version = ret.get("returnVersion")
    year = int(version[:4])
    root = stylesheet_root(year)
    xsl_dir = root / "mef" / "Stylesheets" / str(year)
    header = ret.find("ReturnHeader")
    filing_dln = dln(filing)
    params = {
        "ReturnVersion": version,
        "SubmissionVersion": version,
        "TaxYear": header.findtext("TaxYr"),
        "SubmissionType": header.findtext("ReturnTypeCd"),
        "TIN": filing.ein,
        "DLN": filing_dln or "",
        "DLNLatest": filing_dln or "",
    }
    out = []
    for doc in ret.find("ReturnData"):
        if not isinstance(doc.tag, str):
            continue
        name = doc.tag
        app = etree.fromstring(APPDATA)
        for key, value in (params | {"DocumentId": doc.get("documentId", "")}).items():
            app.find(f"Parameters/{key}").text = value
        app.find("SubmissionHeaderAndDocument").insert(0, copy.deepcopy(header))
        app.find("SubmissionHeaderAndDocument/SubmissionDocument").append(copy.deepcopy(doc))
        out.append((name, _transform(xsl_dir / f"{name}.xsl", app), name in _landscape(year)))
    return out


def render(object_id: str, out_dir: Path, dpi: int = DPI) -> list[Path]:
    """Render a catalog return to `<out_dir>/<object_id>.pdf` and one PNG per page; returns the PNGs."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    filing = corpus.get(object_id)
    if filing is None:
        raise KeyError(object_id)
    docs = documents(object_id)
    asset_root = stylesheet_root(int(filing.return_version[:4]))
    current: dict[str, str] = {}
    missing: set[str] = set()

    def serve(route: Route) -> None:
        path = route.request.url.removeprefix(HOST).split("?", 1)[0]
        if path == "/doc.html":
            route.fulfill(body=current["html"], content_type="text/html; charset=utf-8")
            return
        # Some IRS templates misspell the asset root as /mef/rrdprd/.
        file = asset_root / path.lstrip("/").replace("mef/rrdprd/", "mef/rrprd/", 1)
        if file.name == "990_misc_rev.gif":
            route.fulfill(body=MISC_REVENUE_SVG, content_type="image/svg+xml")
            return
        file = file.with_name(IMAGE_SUBSTITUTES.get(file.name, file.name))
        if not file.is_file():
            # A few images ship only in a neighbouring year's asset folder of the same package.
            file = next(iter(sorted(asset_root.glob(f"mef/rrprd/sdi/versioned/*/images/{file.name}"))), file)
        if file.is_file():
            route.fulfill(path=file)
        else:
            missing.add(path)
            route.fulfill(status=404, body="")

    merged = pdfium.PdfDocument.new()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.route(f"{HOST}/**", serve)
        page.emulate_media(media="print")
        doc_of_page: list[str] = []
        for name, html, landscape in docs:
            sheet_w, sheet_h = LETTER_IN[::-1] if landscape else LETTER_IN
            area_w = (sheet_w - 2 * MARGIN_IN) * CSS_PX_PER_IN
            # A short viewport so scrollHeight measures content, not the window.
            page.set_viewport_size({"width": round(area_w), "height": 100})
            current["html"] = html
            page.goto(f"{HOST}/doc.html", wait_until="load")
            runs, wide = page.evaluate(FIT_JS)
            max_area_h = (sheet_h * MAX_STRETCH - 2 * MARGIN_IN) * CSS_PX_PER_IN
            tallest = max((h for h in runs if h <= max_area_h), default=0)
            # Slack absorbs differences between the screen layout measured here and print layout.
            sheet_h = max(sheet_h, math.ceil(((tallest + SLACK_PX) / CSS_PX_PER_IN + 2 * MARGIN_IN) * 100) / 100)
            pdf = page.pdf(
                width=f"{sheet_w}in",
                height=f"{sheet_h}in",
                margin={side: f"{MARGIN_IN}in" for side in ("top", "bottom", "left", "right")},
                scale=max(0.1, min(1.0, math.floor(area_w / max(wide, 1) * 100) / 100)),
                print_background=True,
            )
            before = len(merged)
            merged.import_pages(pdfium.PdfDocument(pdf))
            doc_of_page += [name] * (len(merged) - before)
        browser.close()
    if missing:
        log.warning("%s: stylesheet assets not in the IRS package: %s", object_id, sorted(missing))

    for stale in out_dir.glob(f"{object_id}_p*.png"):
        stale.unlink()
    pngs: list[Path] = []
    blank = []
    toc: list[dict[str, object]] = []
    for i, pdf_page in enumerate(merged):
        image = pdf_page.render(scale=dpi / 72, grayscale=True).to_pil()
        if image.getextrema() == (255, 255):  # nothing printed on the sheet
            blank.append(i)
            continue
        png = out_dir / f"{object_id}_p{len(pngs) + 1:03d}.png"
        image.save(png)
        pngs.append(png)
        title = document_title(doc_of_page[i])
        if toc and toc[-1]["document"] == title:
            toc[-1]["last_page"] = len(pngs)
        else:
            toc.append({"document": title, "first_page": len(pngs), "last_page": len(pngs)})
    for i in reversed(blank):
        merged.del_page(i)
    merged.save(out_dir / f"{object_id}.pdf")
    (out_dir / f"{object_id}.toc.json").write_text(json.dumps(toc, indent=1))
    return pngs


def document_title(name: str) -> str:
    """Reader-facing name for a return document: `IRS990ScheduleJ` -> `Schedule J (Form 990)`."""
    if m := re.fullmatch(r"IRS990(EZ|PF)?(?:Schedule([A-R]))?", name):
        form = {"EZ": "Form 990-EZ", "PF": "Form 990-PF", None: "Form 990"}[m.group(1)]
        return f"Schedule {m.group(2)} ({form})" if m.group(2) else form
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)


def main() -> None:
    object_id = sys.argv[1]
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else corpus.ROOT / "runs" / "render" / object_id
    start = time.perf_counter()
    pngs = render(object_id, out_dir)
    print(f"{len(pngs)} pages -> {out_dir} in {time.perf_counter() - start:.1f}s")


if __name__ == "__main__":
    main()
