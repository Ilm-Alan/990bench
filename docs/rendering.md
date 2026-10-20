# Rendering returns as page images (document mode)

Goal: show agents page images of a return while the XML stays the ground truth.
Code: `src/bench990/render.py`. Checked 2026-10-19. Every
render ran while the machine had load average ~25–35 from other jobs.

## TL;DR

- **Chosen route: render the XML ourselves with the official IRS MeF stylesheets**:
  XSLT 1.0 in lxml, then headless Chromium (Playwright), then PDF and PNG.
  - The output reproduces the TEOS images. Both carry the same header, `efile GRAPHIC print - DO NOT PROCESS | As Filed Data - | DLN: <DLN>`, and the DLN matches the TEOS image of the same return.
  - On the three test returns, every checked XML value appears on the rendered pages.
  - A render takes about 3–9 s per return.
- **IRS TEOS per-return PDFs can be found programmatically only by brute force, and only some of the time.**
  - The URL pattern is known. Its date component is not published anywhere I could reach.
  - Probing with HEAD requests found 11 of 16 catalog returns.
  - The TEOS search site and its endpoints return HTTP 403 from here.
  - TEOS PDFs are useful as a fidelity reference, but not as a corpus source.

## Route 1: IRS TEOS per-return PDFs

### What works

- **URL pattern, decoded.**
  - The pattern is `https://apps.irs.gov/pub/epostcard/cor/<EIN>_<TAX_PERIOD>_<RETURN_TYPE>_<YYYYMMDD><RETURN_ID>.pdf`.
  - Calibration: the prior-art sample `371589907_202012_990_2021052118162093.pdf` matches the `index_2021.csv` row `18162093,EFILE,371589907,202012,5/21/2021 7:30:52 AM,…,990,93493103007851,202101039349300785`.
  - In that row, the `RETURN_ID` is `18162093` and the date prefix equals `SUB_DATE` (2021-05-21).
- **Downloading a known URL works with plain `curl`.** It returns HTTP 200 and `application/pdf`. A missing file returns a 302 redirect to `irs.gov/404`.

### What does not work

- **The TEOS search UI is blocked.** `https://apps.irs.gov/app/eos/` returns HTTP 403 "Access Denied" (Akamai) to:
  - curl;
  - Playwright headless Chromium;
  - headful Google Chrome (it timed out).
- **The TEOS landing page is blocked too.** `https://www.irs.gov/charities-non-profits/tax-exempt-organization-search` also returns 403.
  - Other irs.gov pages and the `/pub/` files are reachable, so this is probably a regional or bot block `[INFERENCE; not retested from another network]`.
  - I could therefore not inspect the TEOS JSON endpoints.
- **No directory listing.** `/pub/epostcard/cor/` redirects to the 404 page.
- **The date component cannot be looked up.**
  - In `index_2024/2025/2026.csv`, `SUB_DATE` holds only the year (for example `2025`).
  - `RETURN_ID` is blank for 38% / 45% / 48% of rows (449,214 of 728,719; 411,950 of 748,906; 227,026 of 436,239).
  - The DLN's Julian date does not equal the URL date. In the sample, the DLN gives day 103 (2021-04-13); the URL date is 2021-05-21.
- **Brute force: HEAD one URL per candidate day**, counting from the XML `ReturnTs` date (scripts were throwaway, run from `/tmp`).
  - Akamai sometimes answers a burst with 403. Those requests have to be retried, so a 403 does not mean "exists".

  | object_id | form | ReturnTs | result (URL date, offset) |
  |---|---|---|---|
  | 202540209349200809 | 990EZ | 2025-01-11 | found `201609635_202407_990EZ_2025041023334486.pdf` (+89 d) |
  | 202500229349300215 | 990 | 2025-01-22 | found `111700967_202406_990_2025041123357665.pdf` (+79 d) |
  | 202630139349201883 | 990EZ | 2026-01-13 | found `991679424_202412_990EZ_2026061624341911.pdf` (+154 d) |
  | 202510159349302816 | 990 | 2025-01-15 | not found in −30…+500 d |
  | 202500169349100410 | 990PF | 2025-01-16 | found 2025-01-29 (+13 d) |
  | 202403579349300250 | 990 | 2024-12-22 | found 2025-04-11 (+110 d) |
  | 202500219349300135 | 990 | 2025-01-21 | found 2025-04-11 (+80 d) |
  | 202510239349300046 | 990 | 2025-01-22 | found 2025-04-11 (+79 d) |
  | 202403559349200310 | 990EZ | 2024-12-20 | found 2025-04-10 (+111 d) |
  | 202610139349303251 | 990 | 2026-01-07 | found 2026-03-06 (+58 d) |
  | 202610149349200731 | 990EZ | 2026-01-14 | found 2026-06-16 (+153 d) |
  | 202610139349201691 | 990EZ | 2026-01-13 | found 2026-07-29 (+197 d) |
  | 202510159349300741, 202600229349300345, 202630219349300323, 202600139349301660 | 990 | Jan 2025 / Jan 2026 | not found in 0…+259 d |

  - Result: **11 of 16** found. Cost: 260–530 HEAD requests and about 1 minute per return.
  - The dates cluster by posting run. For example, five of the seven returns from batch 2025_01A that were found have URL dates of 2025-04-10 or 2025-04-11.
  - A smarter search could try the known cluster dates first. Even so, about a third of returns had no image within the window, and returns without a `RETURN_ID` cannot be addressed at all.
- **What the downloaded TEOS PDFs look like.**
  - Producer is `GeneratePDFs.exe`, with 1-bit CCITT images at 300 dpi and no text layer.
  - Each page is cropped to its content: 539–541 pt wide and 729–852 pt tall. One Form 990 Part VIII page was 13.25 in tall.
  - Page counts: 17 (2023 990-EZ), 34 (2023 990), 23 (2024 990-EZ).
  - Their header and layout match the MeF stylesheet output. This confirms the prior-art inference that TEOS images are renders of these stylesheets.

## Route 2 (chosen): official MeF stylesheets → HTML → Chromium → PDF/PNG

### Pipeline (`render.py`)

1. **Stylesheets.**
   - For each tax year (taken from `returnVersion[:4]`), the newest package from https://www.irs.gov/e-file-providers/modernized-e-file-mef-stylesheets is downloaded once into `data/stylesheets/` (gitignored):

     | Tax year | Package |
     |---|---|
     | 2019 | `py2022r1` |
     | 2020–2021 | `py2023r1` |
     | 2022–2023 | `py2024r1` |
     | 2024 | `py2025r1` |
     | 2025 | `py2026r1` |
     | 2026 | `py2027r5`, mapped but untested |

   - From each package we extract `mef/Stylesheets/<year>/`, `mef/rrprd/sdi/versioned/*` and `mef/rrprd/common/`, about 60 MB per year. Extraction goes to a staging folder first and is then renamed into place.
   - The zips I downloaded hashed (SHA-256) as follows:
     - `py2024r1` `04756268…e089`
     - `py2025r1` `d9d47b48…1ede5`
     - `py2026r1` `903d2d18…b61a`
2. **XSLT, one document at a time.** Each `ReturnData` child (main form, every schedule, every attached statement such as `OtherExpensesSchedule`, in filing order) is transformed with `Stylesheets/<year>/<ElementName>.xsl`.
   - **Input envelope.** The input is the `AppData` envelope the IRS framework expects:
     - the return header and the one document, with the efile namespace stripped;
     - `Parameters` (SubmissionVersion, TaxYear, DocumentId, TIN, and the DLN from `data/raw/index_<year>.csv`);
     - `FormHeaderGeneric` = `efile GRAPHIC print - DO NOT PROCESS` and `FormHeaderOriginalData` = `As Filed Data`.
   - **Print mode.** We use `Print=separated`, which is the TEOS behaviour: repeating groups that overflow the form's lines move to "Additional Data" tables at the end of each document.
   - **Borrowed screen CSS.** In print mode the stylesheets omit the form's own CSS, so we take it from a second, screen-mode transform of the same document.
   - **Coverage.** Over a random sample of 4,000 filings (65 document types), I found no document type without an XSL.
3. **Chromium.**
   - Each document's HTML is served from a Playwright route at `http://irs.local/`, so the stylesheets' absolute `/mef/rrprd/...` asset paths resolve to the extracted package.
   - It is printed at 100% scale on Letter-width sheets, landscape where the year's `PrintMode.xml` lists the document (Schedules F, I, J, K, N, R, …), with 0.3 in margins.
   - Forced page breaks are measured first. A document's sheet height is stretched up to 1.3× Letter (14.3 in) so that each IRS form page fits on one sheet, as TEOS does. Longer runs, such as long statements or 145-row grant tables, flow across sheets.
4. **Merge and rasterise.**
   - Per-document PDFs are merged with pypdfium2.
   - Fully blank sheets are dropped.
   - Each page becomes a grayscale PNG at 150 dpi.

### How to run

```bash
uv run python -m bench990.render 202500179349301000            # -> runs/render/<object_id>/
uv run python -c "from pathlib import Path; from bench990.render import render; print(render('202630139349201883', Path('/tmp/out')))"
```

- `render(object_id, out_dir, dpi=150) -> list[Path]` writes `<out_dir>/<object_id>.pdf` and `<object_id>_pNNN.png`, then returns the PNG paths.
- `documents(object_id)` returns the per-document HTML. It is useful for text checks.
- **Dependencies added:** `playwright` (Chromium via `uv run playwright install chromium`), `pypdfium2` and `pillow`.

### Verification

- **Test script.** The checks were run with a throwaway script, not committed. For each return it:
  - renders the return;
  - checks named XML values in the PDF text layer (`get_text_bounded`) and in the HTML;
  - computes recall over every `*Amt` / `*Nm` / `BusinessNameLine1Txt` leaf. Amounts are formatted with thousands separators, as printed.
- **Pages were inspected visually** as well.

| Return | Docs | Pages | Render (wall, loaded machine) | PNG / PDF MB |
|---|---|---|---|---|
| 202540209349200809 Brandywine Heights PTC, 990-EZ, 2023v6.0 | 990EZ, A, G, O | 21 | 2.8–5.5 s | 1.6 / 1.0 |
| 202500229349300215 Brookhaven Free Library, 990, 2023v6.0 | 990, A, B, D, O | 35 | 5.8–7.8 s | 3.1 / 1.5 |
| 202500179349301000 Rhode Island Community Food Bank, 990, 2023v6.0 | 990, A, B, C, D, F, G, I, J, L, M, O | 64 | 8.7–9.0 s | 4.8 / 2.9 |

**Named values found on the rendered pages (PDF text layer and HTML):**

- **990-EZ**
  - Part I line 9 total revenue `8,444`
  - officer `KATHERINE KLINICKI`, compensation `0`
  - total assets `61,310`
- **990 (Brookhaven)**
  - Part I total revenue `1,078,308`
  - Part VII `JAMIE PAPANDREA` `123,143`
  - last Part VII person `KRISTIN KIRK-MURPHY`
  - total assets `2,272,685`
- **Large 990 (Rhode Island Community Food Bank)**
  - Part I total revenue `32,759,308`
  - Part VII first person `EDWARD HANDY`; Part VII person 35, `JENNIFER K TOMASSINI`, `156,154`
  - Schedule I recipient 1 `CATHOLIC SOCIAL SERVICES RI`, cash grant `35,000`; last grant `6,950`
  - Schedule J `ANDREW SCHIFF`, base compensation `214,501`
  - Schedule L `MARTHA WOFFORD`

**Leaf recall was 100% for every document of all three returns.** For example:

- Large return: IRS990 362/362, Schedule I 80/80, Schedule J 56/56
- Brookhaven: IRS990 207/207
- 990-EZ: 53/53

**Extra coverage:**

| Return | Pages | Result |
|---|---|---|
| Gary Sinise Foundation 202530169349300143 (Schedule I with 145 recipients) | 64 | Schedule I 583/584 in the PDF text, 584/584 in the HTML. The one PDF miss, `NHL-NASHVILLE HOCKEY`, is a text-extraction artifact: the row is visibly rendered. |
| McLaren 202500159349301465 (TY2022) | 69 | See the Schedule R stylesheet bug below. |
| 2024v5.2 990-EZ 202630139349201883 | 21 | — |
| 990-PF TY2019 / TY2020 / TY2022 | 15–45 | All 100%. |
| 990 TY2021 | — | 100%. |

**Samples (inspected; legible at 150 dpi):**

- `docs/render-samples/202500179349301000_p001_form990_part1.png`: Form 990 page 1, showing total revenue 32,759,308.
- `docs/render-samples/202500179349301000_p051_schedI_grants.png`: Schedule I Part II grants, landscape, Additional Data table.

### Fixes applied to make the official stylesheets work in lxml and Chromium

All of these are in `render.py`:

- **TY2020–2021 missing parameter.** `AddHeader.xsl` uses `$PaperReturnIndicator`, which that year's `CommonPathRef.xsl` never declares, and libxslt aborts. The declaration from TY2022 is injected at load time through an lxml resolver.
- **TY2019 990-PF late attribute.** The stylesheet calls `SetInitialState` after writing child elements. MSXML drops the late attribute; libxslt aborts. On that error we retry with the attribute removed and apply its style (`overflow:visible;height:auto`) to the table containers with CSS.
- **Page breaks on table rows.** Chromium honours page breaks on `<tr>`, which IE ignored, and that produced blank sheets. These breaks are disabled, and any remaining fully blank sheets are dropped.
- **Missing images.**
  - `IRS990.xsl` (TY2022–2024) references `990_Institutional_Trustee_update.gif`, `990_CGGOSA.gif` and `990_misc_rev.gif`, and none of the published packages contains them. The first two are served from same-label siblings. The third is drawn as an SVG reading "Miscellaneous Revenue", the label shown on TEOS images.
  - TY2021's `990_CGGOSAmt_com.gif` exists only in the package's 2022 asset folder, so we fall back to other years' asset folders. Some templates misspell the asset path as `/mef/rrdprd/`, which we map to `/mef/rrprd/`.
- **Screen CSS cleanup.** The borrowed screen CSS would print "Return to Form" buttons and white-on-nothing table headers. Both are fixed to match TEOS: buttons hidden, headers in black.
- **Character encoding.** HTML is serialised as ASCII with character references, because the stylesheets declare ISO-8859-1. Before this fix, the Roman numeral "Ⅵ" came out garbled.

### Fidelity limits

- **Pagination differs from TEOS.**
  - TEOS crops every page to its content height. We use Letter-width sheets with the height stretched per document; on Form 990 the sheets are about 14 in.
  - Page counts therefore differ: 21 vs 17 TEOS pages for the 990-EZ, 35 vs 34 for Brookhaven, 21 vs 23 for the 2024 990-EZ.
  - A Part VII with many people can spill onto a continuation sheet.
- **Some content sits in a different place than on TEOS.**
  - On the 990-EZ, TEOS moves Part III (program services) to Additional Data and keeps Part IV inline; our render does the reverse.
  - We also print an empty "Special Condition Description" box.
  - The likely cause is a different stylesheet revision on the IRS side `[INFERENCE]`.
- **The official stylesheets themselves drop data.**
  - In McLaren's TY2022 Schedule R, Part II has 47 rows, so the rows move to the Additional Data table. That table prints `BusinessNameLine2Txt` but never `BusinessNameLine1Txt`, so 24 of 381 names never appear: not in the HTML and not on the page.
  - The TY2023 and TY2024 `IRS990ScheduleR.xsl` have the same template structure, so the bug probably persists `[INFERENCE from matching reference counts]`.
  - TEOS images presumably share the bug `[INFERENCE]`.
  - **For benchmark questions in document mode, use only fields whose value appears in `documents()` HTML.** Our leaf-recall check does this filtering.
- **Look and colour.**
  - Output is grayscale with anti-aliasing and vector fonts; TEOS is 1-bit at 300 dpi.
  - The stylesheets' gold "Additional Data" title bar prints as light gray.
  - Rows whose fill colour comes from IRS-app user preferences print white.
- **Text layer.** The PDF has a text layer; TEOS has none. Give agents the PNGs (or rasterise again) if text extraction must be impossible.
- **Text-based checks cannot see invisibility.** They cannot detect invisible text (the white header bug was found visually). Spot-check pages visually whenever the CSS changes.
- **Software ID can be blank.** The "Additional Data" header shows a blank Software ID when the document lacks a `softwareId` attribute; this is data-driven.

### Per-return cost

- **Compute.**
  - 3–9 s wall for 21–64 pages on an Apple-silicon Mac under heavy load (load average 25–35). This includes Chromium launch (about 1 s), cached XSLT (about 0.6 s for 12 documents) and PNG encoding.
  - PNG `optimize=True` cost about 8 s per 64 pages for no size gain, so it is off.
  - Extracting a stylesheet year for the first time adds about 5–10 s, once per year.
- **Storage.**
  - About 75 KB per page of PNG at 150 dpi grayscale: 1.6–5.6 MB of PNG per return.
  - The PDF is about half of that.
- **Disk.** About 60–66 MB per tax year of extracted stylesheets, plus 9–32 MB per package zip.
