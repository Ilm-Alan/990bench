# Prior art: LLM/agent benchmarks over IRS Form 990 data

Research date: 2026-10-19. Every claim has a URL. `[UNVERIFIED]` marks claims I could not confirm from a primary source. `[INFERENCE]` marks my own reasoning.

Search coverage: arXiv (API and web), ACL Anthology, the Hugging Face Hub API (models, datasets, and spaces searched for `irs990`, `irs-990`, `form990`, `form 990`, `990-pf`, `nonprofit`, `givingtuesday`, `nccs`, `propublica`, `open990`, `donut-irs`), GitHub (`gh search repos` with 22 query strings plus code search), Kaggle, web search, and IRS, ProPublica, NCCS, GivingTuesday, and Candid primary pages.

---

## Q1. Existing benchmarks, datasets, or projects that evaluate LLMs on 990 data

**Short answer:** No published benchmark, leaderboard, or paper evaluates LLM agents on Form 990 question answering. The closest hits are:
- a single 990 question inside Spider 2.0 (text-to-SQL);
- an early, unevaluated Donut model for 990 extraction;
- many MCP servers that give agents access to 990 data, none with an evaluation;
- a large number of parsed 990 dumps on Hugging Face that have no question/answer pairs.

### 1.1 Spider 2.0: one IRS 990 task (closest direct overlap)
- **URL:** https://arxiv.org/abs/2411.07763 (ICLR 2025). Database folder: https://github.com/xlang-ai/Spider2/tree/main/spider2-lite/resource/databases/bigquery/irs_990
- **Date:** 2024-11-12 (v1), last revised 2025-03.
- **Description:** Spider 2.0 has 632 enterprise text-to-SQL workflow problems over BigQuery, Snowflake, and local databases ([abstract](https://arxiv.org/abs/2411.07763)). It includes an `irs_990` BigQuery database and a Snowflake copy, `IRS_990`. I downloaded `spider2-lite.jsonl` and `spider2-snow.jsonl` and checked them myself. Each file has exactly one 990 task:
  - `bq403` / `sf_bq403`: *"Which three years in 2012-2017 have the smallest absolute difference between median revenue and median functional expenses for organizations filing IRS 990 forms?"*

  The underlying data is the BigQuery/Kaggle "IRS 990" dataset. That dataset is built from the IRS SOI-style extract tables (`irs_990_2012`, `irs_990_ez_2014`, and so on), not the full e-file XML ([Kaggle page](https://www.kaggle.com/datasets/irs/irs-990)).
- **Overlap with our plan:** It confirms that 990 data has appeared in an LLM evaluation, but only as one SQL aggregate question over summary tables.
- **Difference:** There are no schedules, no Schedule I grant chains, no multi-year per-organization lookups, no abstention, and no documents.

### 1.2 `MyroProductoCodo/donut-irs990` (Hugging Face model)
- **URL:** https://huggingface.co/MyroProductoCodo/donut-irs990
- **Date:** Created 2026-03-02 (Hub API).
- **Description:** A Donut model (`naver-clova-ix/donut-base`) fine-tuned to read Form 990 page images and output 1,075 tagged fields. It was trained on a synthetic dataset of 990 images. The model card calls it the author's first fine-tune and an "early checkpoint" with a known tokenizer bug (some field tokens come out as `<unk>`). The card reports no evaluation numbers, and I found no published training dataset `[INFERENCE]`.
- **Overlap:** Same goal as our secondary track (990 image → field values).
- **Difference:** Synthetic training images, no benchmark, no real e-filed renders, no scoring against XML.

### 1.3 FieldBench (document-extraction benchmark)
- **URLs:** https://github.com/fieldbench/corpus, https://pypi.org/project/fieldbench/, https://huggingface.co/fieldbench
- **Date:** Repo created 2026-07-24. PyPI 0.2.3 released 2026-07-28 ([RSS](https://pypi.org/rss/project/fieldbench/releases.xml)).
- **Description:** A schema-driven, field-level extraction benchmark (document → JSON) with 10 categories in the README (the repo tagline says 1,114 documents and 12 categories; the README says 1,441 and 10). It has an `irs_forms` category, but I listed its schemas and they are only `form_w2.yaml` and `form_1099_nec.yaml`; the manifests are `synthetic_1099nec_*` files. **There is no Form 990.** The README warns that about 90% of documents are clean-text extraction rather than rendered pages and that about 47% are synthetic. Its scorer reports a four-way null breakdown: match, miss, hallucination, correct-absence.
- **Overlap:** The extraction-track methodology.
- **Difference:** Different forms. Mostly text input rather than page images.
- **Borrow:** The four-way null scoring and reporting results split by real vs. synthetic documents.

### 1.4 GivingTuesday Data Commons: 990 data plus ML/LLM-adjacent work
- **990 Data Infrastructure** (data lake, curated data marts, EIN API): https://990data.givingtuesday.org/. GivingTuesday has collected and processed IRS filings since 2023.
- **Hugging Face org:** https://huggingface.co/GivingTuesday. Contents (models and datasets dated Nov–Dec 2025):
  - models: `schedule_o`, `NTEE_category_tagging`, `religious_org_v1`, `localities_LNI`;
  - datasets: `NTEE_Training_dataset`, `religious_orgs_training`, `opencorporates_IRS990_EIN_matched_organizations` (786k rows);
  - Space "Annotated 990" (created 2026-01-06, https://huggingface.co/spaces/GivingTuesday/annotated-990): a token-protected API returning tax-year-2023 EINs filtered by annotated attributes (SDG focus, serves elderly, advocacy, staff gender fraction), each with a confidence score.

  These are classification and annotation assets over 990 text (mission, Schedule O). Whether the annotations were produced by an LLM is `[UNVERIFIED]`; the confidence fields suggest a model-generated labeling pipeline `[INFERENCE]`.
- **Generosity AI tools list** (https://ai.givingtuesday.org/tools) includes:
  - "990 Accessibility Enhancer", described as addressing free-text fields where "filings often contain errors";
  - "990 Databaser".

  The detail page did not render past the cookie wall, so its contents are `[UNVERIFIED]`.
- **XML parser repo:** https://github.com/Giving-Tuesday/form-990-xml-parser (2024-02-07).
- **Overlap:** The data substrate and parsing.
- **Difference:** No question answering, no agent evaluation, no benchmark.

### 1.5 MCP servers and "chat with 990" tools: agents already use 990 data, with no evaluation
- **DataDawn MCP** — https://github.com/DataDawn-org/datadawn-mcp (created 2026-05-19, CC0). It exposes 14 tools over a public Datasette 990 database:
  - `search_nonprofit`, `lookup_ein`, `search_grants` (about 12.5M foundation grants), `search_daf_grants`, `org_officers`, `org_grants_made`;
  - `run_990_sql` (arbitrary read-only SQL).

  The README warns agents to filter `return_type IN ('990','990EZ')` to exclude 990-T, and to filter `grant_type='paid'` to exclude future commitments. The schema is at https://github.com/DataDawn-org/990database-public.
- **ProPublica Nonprofit Explorer MCP servers:**
  - https://github.com/pipeworx-io/mcp-propublica-nonprofit (2026-06-26)
  - https://github.com/ccowan190/propublica-nonprofits-mcp (2026-03-13)
  - https://github.com/asachs01/propublica-mcp (2025-06-16)
  - https://github.com/cyanheads/nonprofit-explorer-mcp-server (2026-06-01)
- **Commercial skills and connectors**, seen only in search snippets (details `[UNVERIFIED]`):
  - "IRS 990 Nonprofit Financials MCP Server & Skill — 6 Tools": https://www.mcpbundles.com/skills/irs-990
  - Candid MCP connector: https://www.scalekit.com/connectors/candidmcp
- **NL→SQL apps:**
  - https://github.com/SaveOregonSchools/irs990-tool (2026-06-11): plain-English questions via Ollama, producing "validated, read-only SQL" over a local SQLite database built from 990 XML.
  - https://github.com/ejbarton5554/990-toolkit (2026-02-22): a schema concordance builder that also contains `src/irs990_agent.py`, an "agentic 990 parser".
  - CauseWriter "Nonprofit 990 AI Analyzer" (a custom GPT): https://causewriter.ai/resources/990-analyzer

  None of these ships an evaluation set or accuracy numbers (I checked the READMEs of the GitHub items).
- **Overlap:** These are essentially candidate tool environments for our agent track. The DataDawn tool set closely matches the tools we would give an agent.
- **Difference:** No ground-truth questions, no scoring.

### 1.6 Parsed 990 corpora on Hugging Face (data only, no questions)
- `mauricedalton/irs-990` — https://huggingface.co/datasets/mauricedalton/irs-990 (2026-06-10, gated, cc0-1.0): 6.2M e-filed 990/990-EZ filings parsed into 15 parquet tables, 160.4M rows, tax years 2010–2026, queryable with DuckDB.
- `piercewetter3/irs-990-parsed` — https://huggingface.co/datasets/piercewetter3/irs-990-parsed (2026-05-19; card dated 2026-08-17; CC0):
  - 34 tables: `Charities` (3.6M filer-years), `Grants` (26.2M Schedule I / 990-PF grants), `Officers`, `Contractors`;
  - grantee name→EIN resolution tables (`AuthoritativeEin`, `name_mapping`, `base_name_ein`, `Backfill`);
  - joined to FEC, OFAC, PPP, Medicare, and DOT data.

  The card is tagged `question-answering`, but it contains no questions. The grantee EIN resolution tables are directly relevant to Schedule I chains.
- Others, all data dumps:
  - `healthparse/us-nonprofit-health-org-finances-990` (2026-05-31, CC0);
  - `CommunityOne/one-nonprofits-*` (2026-05-02);
  - `zalizedata/...-restricted` (commercial, gated).
- GitHub: https://github.com/FraudHawker/nonprofit-filings (2026-06-01) — 990s cross-linked by EIN with FEC, DOL, FAC, lobbying, and state registries.
- **Overlap:** Ready-made relational 990 databases. Useful for cross-checking our own parser.
- **Difference / implication:** No questions. Because these are public, parsed values are easy to retrieve and may already be in pretraining data `[INFERENCE]`.

### 1.7 Kaggle / BigQuery "IRS 990" dataset
- **URL:** https://www.kaggle.com/datasets/irs/irs-990
- **Description:** A BigQuery dataset of e-filed 990, 990-EZ, and 990-PF data (the same source as the Spider 2.0 database). Other Kaggle uploads, such as https://www.kaggle.com/datasets/katyali/irs-990-2020, are analysis datasets. I found no Kaggle competition or question/answer set on 990 data.

### 1.8 Academic NLP and network work using 990 data (not LLM agent evaluation)
- **ANGEL: Enterprise Search System for the Non-Profit Industry** — Haq, Sharma, Bhattacharyya, EMNLP 2023 Industry: https://aclanthology.org/2023.emnlp-industry.77/
  - ColBERT-based funder↔grantee matching from mission text.
  - Built a "non-profit-search database" of 594K fund-givers and 194K fund-seekers from 990 filings.
  - Expert-annotated evaluation of 463 funders × 100 seekers.
  - **Overlap:** Funder–grantee relationships.
  - **Difference:** Retrieval and ranking by mission similarity, not tool-using question answering over filed grant records.
- **Mapping Philanthropic Support of Science** — Shekhtman, Gates, Barabási, arXiv 2206.10661, 2022-06-09: https://arxiv.org/abs/2206.10661
  - Built a bipartite funder→recipient network from tax forms of 685,397 nonprofits; about 1M science and higher-education grants.
  - Findings: grant relationships persist over time, and the network predicts future funder–recipient links.
  - **Overlap:** The grant-network structure we would query.
  - **Difference:** Network science, not LLMs.
- **LLM-aided extraction for a local nonprofit** (arXiv 2511.18483) and **LLMs in nonprofit program evaluation** (arXiv 2510.19799) are unrelated to 990 filings (titles from the arXiv API results).

### 1.9 Other near misses named in the assignment
- **ProPublica Nonprofit Explorer** — https://projects.propublica.org/nonprofits/ and the API at https://projects.propublica.org/nonprofits/api
  - Organization/filing JSON (summary financials from the SOI extract).
  - HTML full-text renders of e-filed XML, with the viewer adapted from https://github.com/betson/irs-efile-viewer.
  - PDF links.
  - Full-text search of filings.
  - Not a benchmark. Terms in §3.2.
- **IRSx (990-xml-reader)** — https://github.com/jsfenfen/990-xml-reader (2017; still maintained, last push 2026-09-22). Details in §3.4.
- **Nonprofit Open Data Collective concordance** — https://github.com/Nonprofit-Open-Data-Collective/irs-efile-master-concordance-file. Details in §3.4.
- **NCCS efile database** — https://urbaninstitute.github.io/nccs/datasets/efile/. Details in §3.4.
- **Open990** — https://www.open990.com/ (by 990 Consulting; tools at https://github.com/990consulting/open990odl). GuideStar says Open990.org Inc "has not appeared on the IRS Business Master File in a number of months" (https://www.guidestar.org/profile/84-1842054). Possibly defunct `[UNVERIFIED]`.
- **CitizenAudit** — https://www.citizenaudit.org/. A commercial search engine over "2.5 Million Nonprofits, 30 Million Documents, 4+ Billion Pages" with grant search. Not a benchmark.
- **Charity Navigator 990 toolkit** — https://github.com/CharityNavigator/irs990 and http://990.charitynavigator.org/ (ETL).
- **Unrelated tax-document benchmark:** `Extend-AI/PoliTax-Split` (https://huggingface.co/datasets/Extend-AI/PoliTax-Split, 2026-03-30, CC0) is a page-splitting and classification benchmark on 30 presidential *1040* return PDFs. It shows that tax-form document benchmarks exist, but not for 990.

---

## Q2. Closest analogous benchmarks (filings / finance / agents / contamination resistance)

| Benchmark | URL / date | Task and data source | Labels | Size | Agentic? |
|---|---|---|---|---|---|
| **Vals AI Finance Agent Benchmark (FAB v1.1)** | https://arxiv.org/abs/2508.00828 (2025-05-20); leaderboard https://www.vals.ai/benchmarks/finance_agent (updated 2026-06-04); harness https://github.com/vals-ai/finance-agent | Financial-analyst research questions over recent SEC filings, in 9 task categories | **Human expert-authored** and reviewed (quality control by AfterQuery experts in v1.1); **LLM-as-judge** grading (GPT-5.2, mode of 3 runs in v1.1) | 537 questions: 50 public validation, 150 private validation (licensed), 337 test (permanently private) | **Yes.** Tools: EDGAR search (SEC_API), web search (Tavily in v1.1), ParseHTML, RetrieveInformation, `submit` tool. Reports cost, latency, and tool-call counts. Top score 64.37% (Claude Opus 4.7). |
| **FinanceBench** | https://arxiv.org/abs/2311.11944 (2023-11-20) | Open-book question answering on public-company filings | Human-written questions with answers and **evidence strings**; model answers manually reviewed (n=2,400) | 10,231 questions; 150 open-sourced | No (RAG / long-context). Notes that GPT-4-Turbo with retrieval answered incorrectly or refused 81% of the time. |
| **TAT-QA** | https://arxiv.org/abs/2105.07624 (2021-05-17) | Hybrid table + text question answering from real financial reports, with numerical reasoning | **Human annotators** with financial backgrounds (paper §3) | 16,552 questions, 2,757 contexts, 182 reports | No |
| **DocFinQA** | https://arxiv.org/abs/2401.06915 (2024-01-12) | Long-document version of FinQA: full filing as context (average 123k words) | Inherited from FinQA (human-annotated) | 7,437 questions | No (long context / RAG) |
| **SEC-QA** | https://arxiv.org/abs/2406.14394 (2024-06-20) | Multi-document financial question answering over 10-K, 10-Q, and 8-K filings (18 S&P 500 companies, 2010–2023, 10 metrics) | **Semi-automatic / computed.** Templates filled from a key-value-document table T(company, year, metric, value, document). "Generated automatically from an existing financial database without any involvement of human annotators" (§Limitations of the PDF). Refreshable with new filings. | "Flexible" (generated on demand) | Partly. Their best system is program-of-thought with `select_document`, `retrieve_relevant_pages`, and `extract_value` tool functions. **This is the closest methodological analog to our plan.** |
| **τ-bench** | https://arxiv.org/abs/2406.12045 (2024-06-17) | Tool-agent-user conversations (retail, airline) with domain policies | Annotated goal database state; scoring compares the final database state | Retail + airline task sets | **Yes.** Introduces **pass^k** reliability (gpt-4o pass^8 <25% in retail). |
| **LiveBench** | https://arxiv.org/abs/2406.19314 (2024-06-27) | Contamination-limited general benchmark built from recent sources | **Objective ground truth**, automatic scoring, no LLM judge | Monthly updates; questions released over time | No |
| **Spider 2.0** | https://arxiv.org/abs/2411.07763 (2024-11-12) | Enterprise text-to-SQL over large real schemas (more than 1,000 columns); includes the IRS 990 database (§1.1) | Gold SQL / execution results | 632 tasks (547 in -lite / -snow) | Yes (code agent) |
| **DABstep** | https://arxiv.org/abs/2506.23719 (2025-06-30); leaderboard https://huggingface.co/spaces/adyen/DABstep | Multi-step data analysis over payments data plus documentation | **Factoid answers with automatic correctness checks** | About 450 tasks; best agent 14.55% on the hard tasks | Yes (code-based) |
| **TaxCalcBench** | https://arxiv.org/abs/2507.16126 (2025-07-22); https://github.com/column-tax/tax-calc-bench | Compute personal 1040 returns from complete inputs | **Computed by a traditional tax engine** (paper §1) | 51 test cases (TY24) | No. Models get fewer than one-third of returns right. |
| **AbstentionBench** | https://arxiv.org/abs/2506.09038 (NeurIPS 2025 D&B) | Abstention on unanswerable or underspecified questions across 20 datasets | Dataset-provided labels | 20 datasets | No. Finds reasoning fine-tuning *degrades* abstention by 24% on average. |

Other related items, mentioned for completeness:
- The Stanford EDGAR Filings Dataset (https://arxiv.org/abs/2606.18192, 2026-06) converts SEC filings into pretraining data. This shows that regulatory filings are being put into training corpora on purpose, which is a contamination signal for any static filings benchmark `[INFERENCE]`.
- Mint-Agent (https://arxiv.org/html/2608.16386v2) builds agentic finance tasks "from primary financial materials" aligned to EDGAR structured values (seen in snippet only; `[UNVERIFIED]` details).

**How these differ from our plan:**
- All of the filing-based agent and QA benchmarks use **SEC/EDGAR corporate filings**.
- Only SEC-QA and TaxCalcBench compute labels from structured data. FAB, FinanceBench, and TAT-QA are human-labeled.
- None covers nonprofit filings, entity-to-entity grant graphs, or a monthly government XML feed.

---

## Q3. Data-access facts

### 3.1 Rights / terms for IRS 990 XML
- **IRS website content:** "Content on this website that was created or maintained by federal employees in the course of their duties is not subject to copyright and may be freely copied. Credit is requested." It also restricts use of IRS/Treasury seals and names in ways that imply endorsement (18 U.S.C. §701, 31 U.S.C. §333). Source: https://www.irs.gov/about-irs/use-of-content-from-irsgov
- **Legal basis for disclosure:** Exempt-organization returns are public by statute. 26 U.S.C. §6104 says annual returns "shall be made available by the Secretary to the public" (https://www.law.cornell.edu/uscode/text/26/6104). The Taxpayer First Act mandated e-filing and release in machine-readable format (described in the NODC comment letter, https://www.reginfo.gov/public/do/DownloadDocument?objectID=150472000).
- **Licensing caveat:** The filing *content* is written by the filers, not by federal employees. So "public domain" is the community's working assumption, not an explicit IRS license.
  - The old AWS Registry entry lists **"License: None"** (https://registry.opendata.aws/irs990/).
  - Downstream redistributors label their derived data CC0: mauricedalton, piercewetter3, healthparse on Hugging Face; DataDawn on GitHub.
  - `[INFERENCE]` Redistribution is low-risk: the content is statutorily public, the IRS states no restrictions, and there is widespread CC0 redistribution. **Not legal advice.** Avoid IRS seals and branding in our benchmark.
- **Bulk XML access, current state:** https://www.irs.gov/charities-non-profits/form-990-series-downloads
  - Monthly ZIPs, e.g. `https://apps.irs.gov/pub/epostcard/990/xml/2026/2026_TEOS_XML_01A.zip`, from 2019 onward, plus a yearly index CSV.
  - The TEOS bulk page says "Latest data posting XML: August 20, 2026" (https://www.irs.gov/charities-non-profits/tax-exempt-organization-search-bulk-data-downloads). Data sets "are updated monthly."
  - The 2026 listing ends at `08A`.
- **AWS feed (historical):** The IRS stopped updating the AWS `s3://irs-form-990` feed after 2021-12-31, and the registry entry is now **deprecated**: "the historic data will no longer be available" (https://registry.opendata.aws/irs990/).
- **Index CSV schema** (I downloaded 2025 and 2026): `RETURN_ID, FILING_TYPE, EIN, TAX_PERIOD, SUB_DATE, TAXPAYER_NAME, RETURN_TYPE, DLN, OBJECT_ID, XML_BATCH_ID` (https://apps.irs.gov/pub/epostcard/990/xml/2025/index_2025.csv). Quirks I observed:
  - `RETURN_ID` is **blank for many rows**.
  - `RETURN_TYPE` includes **990T** alongside 990, 990EZ, and 990PF.
  - `TAX_PERIOD` can be years before the release year (for example, 202212 in the 2025 index).
  - EINs with leading zeros appear as strings (e.g. `042702867`).
- **Supporting artifacts:**
  - Official schemas: TEOS schemas page (https://www.irs.gov/charities-non-profits/tax-exempt-organization-search-teos-schemas) and MeF schema pages (https://www.irs.gov/e-file-providers/current-valid-xml-schemas-and-business-rules-for-exempt-organizations-and-other-tax-exempt-entities-modernized-e-file).
  - Annotated forms mapping form fields to the dataset: https://www.irs.gov/charities-non-profits/tax-exempt-organization-search-teos-annotated-forms
  - Dataset guide, Pub 5891: https://www.irs.gov/pub/irs-pdf/p5891.pdf

### 3.2 Rendered PDFs of e-filed returns
- **IRS TEOS per-return PDFs exist for e-filed returns, and they are XML renders.**
  - Example: https://apps.irs.gov/pub/epostcard/cor/371589907_202012_990_2021052118162093.pdf (I downloaded it; HTTP 200, 31 pages).
  - The page header reads **"efile GRAPHIC print - DO NOT PROCESS | As Filed Data - | DLN: 93493103007851"**.
  - It is **image-only**: producer "Tiff Junction 4.1", 1-bit CCITT images at 300 dpi, no text layer (`pdftotext` returns nothing).
  - The DLN is in both the page header and the XML index CSV, so PDFs can be joined to XML exactly `[INFERENCE: join key confirmed present in both; I did not test a join]`.
  - URL pattern: `cor/<EIN>_<TAXPERIOD>_<FORM>_<timestamp>.pdf`.
  - The IRS says returns filed since January 2018 can be viewed free on TEOS (https://www.irs.gov/charities-non-profits/copies-of-eo-returns-available).
  - In Nov. 2024, NODC asked the IRS for an EIN/tax-period→PDF-URL index because "There is no way, however, to link directly to the individual PDF files hosted by the IRS" ([comment letter, §2e](https://www.reginfo.gov/public/do/DownloadDocument?objectID=150472000)). I found no such index on the IRS pages today.
- **IRS bulk PDF downloads appear to have been withdrawn.**
  - A Wayback snapshot from June 2024 says "download ... filings on record in PDF and XML formats" and links per-year pages (`/form-990-series-downloads-2018` … `-2023`): https://web.archive.org/web/20240614114235/https://www.irs.gov/charities-non-profits/form-990-series-downloads
  - The 2023 PDF page (snapshot 2025-06-18) listed about 190 ZIPs like `https://apps.irs.gov/pub/epostcard/990/2023/01/download990pdf_01_2023_prefixes_01-26.zip`.
  - **Today**, the downloads page says "XML formats" only. The per-year PDF pages return **404**, and that sample PDF ZIP **redirects to irs.gov/404** (checked 2026-10-19).
  - The exact removal date is `[UNVERIFIED]`. The Wayback CDX shows the 2023 PDF page last archived 2025-11-10.
  - ProPublica's API docs still say "Bulk PDF downloads since 2017 are available from the IRS" (https://projects.propublica.org/nonprofits/api). That statement looks out of date `[INFERENCE]`.
- **Official IRS rendering stylesheets (a key enabler for the extraction track).** MeF stylesheets (XSL/CSS) "can be used by external stakeholders to display ... exempt organizations ... returns" and are published per tax year from 2008 to TY2026 (https://www.irs.gov/e-file-providers/modernized-e-file-mef-stylesheets).
  - The page notes a TY2022 Form 990 stylesheet header fix and says it did not affect "the accuracy of Forms 990 images that appear on Tax Exempt Organization Search".
  - That wording, together with the "efile GRAPHIC print" header, strongly suggests TEOS images are produced from the XML with these stylesheets `[INFERENCE]`.
  - We could render any XML → HTML → PDF/PNG ourselves with the official stylesheets. That gives unlimited, fresh, exactly aligned image/ground-truth pairs.
- **ProPublica Nonprofit Explorer PDFs and renders** (https://projects.propublica.org/nonprofits/api):
  - `pdf_url` links to scanned or original 990 PDFs ("rate limited").
  - Pre-2017 documents were obtained via Public.Resource.org.
  - E-filed returns also get HTML renders, e.g. https://projects.propublica.org/nonprofits/organizations/810861541/202513219349328476/IRS990
  - Organization pages note "Duplicate download links may indicate a resubmission or amendment" (http://projects.propublica.org/nonprofits/organizations/810861541).
  - **Terms:** API use "constitutes agreement" to ProPublica's Data Terms of Use (https://www.propublica.org/about/propublica-data-terms-of-use → https://projects.propublica.org/datastore/terms/). Those terms say: you can't republish the raw data in its entirety or distribute it stand-alone; can't change it except to correct it; can't sublicense or resell it; must cite ProPublica; accuracy not guaranteed.
  - **Implication:** Source PDFs and XML from the IRS, not ProPublica, if we plan to redistribute `[INFERENCE]`.
  - History: in 2014 PDFs were temporarily removed over unredacted SSNs (API changelog, same URL). This is a PII caution for scanned or paper returns.

### 3.3 Known XML pitfalls and data-quality issues
- **Schema versioning and renamed fields.**
  - "The IRS has released 30+ versions of the 990 XML schema since 2009 ... renamed many fields — e.g. `BaseCompensationFilingOrgAmt` (2013) → `BsCmpnstnFlngOrgAmt` (2016)" (https://github.com/ejbarton5554/990-toolkit).
  - That builder lists 2018v3.0 through 2024v5.0 sub-versions and warns that pre-2013 schemas are "significantly different".
  - NODC told the IRS that "2022 had many more schemas than just versions 4 through version 7" and that the schemas posted on TEOS are incomplete ([comment letter](https://www.reginfo.gov/public/do/DownloadDocument?objectID=150472000)).
- **IRSx** (https://github.com/jsfenfen/990-xml-reader, MIT):
  - Parses 990, 990-EZ, 990-PF, and Schedules A–O and R into standardized JSON for schema versions **2013+**, with CSV/TXT back to 2010.
  - JSON variable names are canonicalized to **2016v3.0**.
  - CSV/TXT output includes **version-specific form line numbers and descriptions**; metadata lives in https://github.com/jsfenfen/990-xml-metadata (`variables.csv`, `groups.csv`, `line_numbers.csv`, `descriptions.csv`).
  - Unknown xpaths are logged as "keyerrors".
  - `irsx_retrieve` scrapes the IRS downloads page (2019+).
- **NODC Master Concordance File** (https://github.com/Nonprofit-Open-Data-Collective/irs-efile-master-concordance-file, **ODC-By 1.0**):
  - Maps about 10,000 unique xpaths onto a consistent data dictionary.
  - Fields: `variable_name, xpath, description, form, form_part, form_line_number, location_code` (e.g. `F990-PC-PART-01-LINE-02`), `versions`, `latest_version`, `rdb_table`.
  - About 125 tables (about 80 one-to-one, 46 one-to-many).
  - Includes a 990-EZ↔990 Part I crosswalk, needed because EZ financial lines are composites of full-990 fields.
- **Newer NCCS / NODC stack** (https://urbaninstitute.github.io/nccs/datasets/efile/):
  - 990/990-EZ split into 131 tables and 990-PF into 80 tables, published per tax year as CSV and Parquet (efile_v3_1, published 2026-10-09).
  - Data dictionaries via `concordance990`; `panel990` R package for multi-year panels.
  - R tooling: https://github.com/Nonprofit-Open-Data-Collective/irs990efile, https://github.com/Nonprofit-Open-Data-Collective/ef2
- **Coverage bias before 2021.** E-filing was voluntary for most organizations until TY2021 (mandatory before that only for organizations with more than $10M assets and, after July 2019, private foundations). Pre-2021 waves skew toward larger organizations. Counts: about 51k e-filed returns for TY2009 vs. about 694k for TY2023. The latest tax year is always partial; it "can take two to three years" for most returns to be released (NCCS page above).
- **Missing grant data — directly relevant to Schedule I and 990-PF grant questions** (Candid / NODC comment to IRS, 2024-11-05, https://www.reginfo.gov/public/do/DownloadDocument?objectID=150472000):
  - At least 1,957 foundations with more than $5B in grants had grantee information missing from FY2021 990-PF XML.
  - Of 521 FY2022 returns with no grant listing in XML, 41% (212) had no listing in the PDF either. About $4.3B in grants is unreported in either format.
  - Common patterns: partial grant lists that point to attachments, and single "grants" to recipients named "See attachment", "Schedule available", or "See Line 3A statement".
  - Part VII trustee/staff compensation attachments are missing, and Part I totals disagree with the compensation detail.
  - **990-PF does not require grantee EINs** (Part XIV 3a/3b), while Schedule I on Form 990 does. That makes private-foundation grant chains much harder to resolve by EIN.
- **Duplicates and amendments.** Multiple filings can exist per EIN per tax period because of resubmissions or amendments (ProPublica note above). Our answer-computing code needs a deterministic "which return counts" rule, e.g. latest amended `[INFERENCE]`.
- **Redaction.** Some sensitive information, notably Schedule B donor identities, is redacted (NCCS efile page linking https://www.adlercolvin.com/blog/2015/06/08/exempt-organizations-can-redact-donor-identifying-information-from-irs-form-990-schedule-b-before-public-disclosure/).
- **Release delays.** In 2020–2023, release delays lasted "almost three years". NODC also asked the IRS to restore a lightweight index, since users otherwise must download more than 1 TB to find updated returns (comment letter above).
- **Free-text quality.** GivingTuesday says filings "often contain errors" in free-text fields (https://ai.givingtuesday.org/tools, "990 Accessibility Enhancer" blurb).

---

## Q4. LLM agents following Schedule I grant relationships or nonprofit financial networks

**I found no paper, benchmark, or project that evaluates LLM agents on following Schedule I / 990-PF grant chains.** What exists:
- **Network analysis without LLMs:** Mapping Philanthropic Support of Science (https://arxiv.org/abs/2206.10661) builds a funder–recipient bipartite network from 990 data and studies link persistence and prediction.
- **Retrieval-based matching:** ANGEL (https://aclanthology.org/2023.emnlp-industry.77/) matches funders and seekers by mission text, with expert-scored relevance.
- **Agent tools without evaluation:** DataDawn MCP's `search_grants`, `org_grants_made`, and `search_daf_grants` (https://github.com/DataDawn-org/datadawn-mcp) let agents walk grant edges, but there are no tasks or scores.
- **Pre-resolved grant graphs:**
  - `piercewetter3/irs-990-parsed`: 26.2M grants plus grantee name→EIN resolution tables (https://huggingface.co/datasets/piercewetter3/irs-990-parsed).
  - Grant dashboards: https://github.com/akbknight/form990-grant-miner, a pipeline that extracts 9.7M+ grant records from 990 XML.
- **Entity-resolution motivation:** Candid's finding that 990-PF lacks grantee EINs and that attachments are missing ([comment letter](https://www.reginfo.gov/public/do/DownloadDocument?objectID=150472000)) means grant chains through private foundations need name and address matching. That is a natural hard tier, or an abstention trigger.

---

## Verdict

**Novelty.** As far as I searched (arXiv, ACL Anthology, HF Hub API, GitHub, Kaggle, web), **a tool-using agent benchmark over IRS 990 e-file data is novel.** Specifically, nothing combines:
- code-computed answers from the XML;
- multi-year per-organization comparisons;
- Schedule I grant-chain traversal;
- cross-organization rankings;
- unanswerable questions requiring abstention.

The extraction track is also effectively unclaimed. The only 990-specific extraction artifact is an early, unevaluated Donut checkpoint trained on synthetic images, and FieldBench's IRS category covers only W-2 and 1099-NEC.

**Closest items (ranked):**
1. **SEC-QA:** the same idea (computed answers from a structured database with document provenance, refreshable) applied to SEC filings.
2. **Vals Finance Agent Benchmark:** the same agentic harness concept over EDGAR, but with human-written questions and an LLM judge.
3. **Spider 2.0 `bq403`:** the only existing LLM evaluation item over 990 data (one SQL question on SOI summary tables).
4. **DataDawn MCP / ProPublica MCP servers:** effectively our tool environment, without tasks.
5. **`donut-irs990` and FieldBench:** extraction-track precedents.
6. **DABstep, TaxCalcBench, LiveBench, τ-bench, AbstentionBench:** methodology.

**Ideas to borrow:**
- **Computed labels plus templates plus provenance (SEC-QA).**
  - Generate questions from a value table T(EIN, tax_period, field, value, object_id).
  - Use SEC-QA's complexity axes: parallel reference (multi-year), multi-hop (grant chain), structural reference (named Part or Schedule), multi-output.
  - Keep `object_id` and xpath per answer so you can score evidence and retrieval, not just the final answer.
- **Splits and leaderboard hygiene (Vals FAB).**
  - Small public validation set, a licensed or private validation set, and a permanently private test set.
  - Report cost per test, latency, and tool-call counts.
  - Require a `submit` tool for the final answer.
  - Pin "as-of" dates in questions. Vals moved from relative dates to absolute ones; for us that means the IRS release month.
- **Contamination resistance (LiveBench / SEC-QA refresh).**
  - Build each monthly release only from returns first posted in the newest IRS monthly ZIP (`XML_BATCH_ID`).
  - Large organizations' values are already widely mirrored (ProPublica, Candid, CC0 Hugging Face dumps), so stratify by organization size and freshness `[INFERENCE]`.
- **Reliability metric (τ-bench).** Report pass^k across repeated runs, not only pass@1.
- **Exact-match scoring without an LLM judge (DABstep, LiveBench, TaxCalcBench).**
  - Use factoid formats (integer dollars, EIN, year, ranked list) with deterministic checks.
  - Reserve LLM judging, if used at all, for free-text answers.
- **Abstention tier (AbstentionBench, FinanceBench refusals).**
  - Draw unanswerable questions from known data gaps: tax year not yet released; 990-EZ filers asked for full-990-only fields; Schedule B redactions; Candid-style missing grant lists or "See attachment" recipients; 990-PF grantees with no EIN.
  - Make sure the ground truth is "not determinable from the filings", not zero.
- **Extraction-track scoring (FieldBench).**
  - Use the four-way null breakdown (match / miss / hallucination / correct-absence).
  - Stratify results by real TEOS images vs. our own MeF-stylesheet renders.
  - Pair TEOS image-only PDFs with the XML via DLN or object ID.
  - Use the official IRS MeF stylesheets to render fresh, perfectly aligned documents.
- **Schema handling.**
  - Use IRSx canonical names (2016v3.0) and/or the NODC concordance (ODC-By; attribution required) to map xpaths across 30+ schema versions.
  - Expose form line numbers and descriptions to agents, the way IRSx's TXT output does.
- **Return selection rules.**
  - Define amendment and duplicate resolution, exclude 990-T, and handle blank `RETURN_ID` before computing answers.
  - Publish these rules with the benchmark.
- **Licensing.**
  - Source everything from IRS endpoints.
  - Do not redistribute ProPublica API data (their terms forbid stand-alone redistribution).
  - Credit the IRS and avoid IRS seals.
  - Attribute NODC if we ship concordance-derived mappings.
