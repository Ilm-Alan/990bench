# Data available on this workstation

Everything here is public IRS data, read-only. There is no internet access. Python 3.12 with
pandas, lxml and inflate64, `unzip`, `7z` and standard Unix tools are installed. Write your files
under `/work`.

## /data/irs

### Form 990-series e-file returns (XML)

- `index_2024.csv`, `index_2025.csv`, `index_2026.csv`: one row per return the IRS released that
  year. Columns: `RETURN_ID, FILING_TYPE, EIN, TAX_PERIOD (YYYYMM, the month the tax period ends),
  SUB_DATE, TAXPAYER_NAME, RETURN_TYPE (990, 990EZ, 990PF, 990T), DLN, OBJECT_ID, XML_BATCH_ID`.
- `<batch>.zip`: the returns in each release batch. Each member is `<OBJECT_ID>_public.xml`; some
  members are nested in a folder inside the zip.
  - Zip file names use an upper-case suffix letter (`2024_TEOS_XML_04A.zip`) even where the index
    writes it in lower case (`2024_TEOS_XML_04a`).
  - The IRS split two large batches across two zips but labels all of their returns with the first
    name in the index: returns indexed as `2025_TEOS_XML_05A` are in `2025_TEOS_XML_05A.zip` or
    `2025_TEOS_XML_05B.zip`, and likewise for `2026_TEOS_XML_05A`.
  - Some zips (for example `2025_TEOS_XML_11B.zip`) are compressed with Deflate64, which Python's
    `zipfile` cannot read. `unzip` and `7z` can, and the `inflate64` package can inflate the raw
    entries.
- Each XML file is one complete return as filed: a `ReturnHeader` (filer EIN, name, address, tax
  year, tax period begin and end dates, return type) and `ReturnData` holding the main form
  (`IRS990`, `IRS990EZ` or `IRS990PF`) and every schedule filed with it (`IRS990ScheduleA` …
  `IRS990ScheduleR`). Elements are in the namespace `http://www.irs.gov/efile` and follow the IRS
  Modernized e-File (MeF) schemas. An amended return sets `AmendedReturnInd` in the main form.

### Exempt Organizations Business Master File

- `bmf_eo1.csv` … `bmf_eo4.csv`: the IRS's current register of tax-exempt organizations, split by
  region. Includes EIN, name, street, city, state, ZIP, subsection, ruling date, NTEE code and the
  latest asset, income and revenue amounts on record.

### Other

- `SHA256SUMS`: checksums of the files above.
