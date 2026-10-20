# Data available on this workstation

Everything here is public IRS data, read-only. There is no internet access. Python 3.12 with
pandas, and standard Unix tools, are installed. Write your files under `/work`.

## Returns

Returns are available only as page images, the way the IRS publishes them. Use the `open_return`
tool with a return's OBJECT_ID to see its pages and which form or schedule each page belongs to,
and `view_page` to look at a page.

## /data/irs

- `index_2024.csv`, `index_2025.csv`, `index_2026.csv`: one row per Form 990-series return the
  IRS released that year. Columns: `RETURN_ID, FILING_TYPE, EIN, TAX_PERIOD (YYYYMM, the month
  the tax period ends), SUB_DATE, TAXPAYER_NAME, RETURN_TYPE (990, 990EZ, 990PF, 990T), DLN,
  OBJECT_ID, XML_BATCH_ID`. Form 990-T returns are not available as images.
- `bmf_eo1.csv` … `bmf_eo4.csv`: the IRS Exempt Organizations Business Master File, its current
  register of tax-exempt organizations, split by region. Includes EIN, name, street, city, state,
  ZIP, subsection, ruling date, NTEE code and the latest asset, income and revenue amounts on
  record.
