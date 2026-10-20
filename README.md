# 990bench

Can AI agents do nonprofit due diligence from IRS filings? A research log: an agent harness over
1.85 million real Form 990-series returns, ground truth computed by code and checked
independently, a small reliability study, and what held up and what did not.

This is not a leaderboard. The study ran one cheap model across settings, one weak model at one
setting, and no strong model, so read the numbers as findings about failure modes, not rankings.

## Findings

Full write-up with tables, intervals and limitations: [docs/report.md](docs/report.md).

1. **Values right, packets wrong.** DeepSeek v4.1 Flash read at least 98.3% of graded values
   correctly in every run that finished, but only 16 of 32 due-diligence packets were fully
   correct. Rare per-value errors compound over 60–240 values per packet.
2. **One undefined term cost a quarter of the outcome.** Asked for "tax year 2024", the model
   picked the wrong year's return for every organization with a non-December fiscal year in two of
   four runs (10 wrong returns). One sentence defining the term removed all of them.
3. **The misreads are not about resolution.** Reading 193 values from dense tables outside an
   agent run, the model was 99.0–100% right whether it saw the full page at 150 or 300 dpi or a
   zoomed strip of the row (no significant paired difference). I ran this cheap test before
   building a zoom tool; the result said not to build it. One misread, shown in
   [docs/example.md](docs/example.md), persisted at both resolutions.
4. **Bad scans cost tokens before accuracy.** On coarse 1-bit pages the model never submitted a
   wrong value; it ran out of token budget in all four runs, re-reading pages.

## How it works

An agent gets an analyst's request, for example: for these 10 grant applicants (name, city and
state), report the EIN, tax-period end, total revenue, program-expense share, top Part VII
compensation and whether Schedule L reports insider transactions, from each tax-year-2024 Form 990.
It works in a network-less Docker sandbox with the IRS index files and Business Master File as
CSVs. Returns exist only as page images, rendered from the IRS XML with the IRS's own display
stylesheets; the agent opens them with `open_return` (table of contents) and `view_page`. The
answer is a JSON file that passes only if every value is right.

Why the answers can be trusted:

- Answers are computed from the XML, then recomputed by a second route (the IRS index and direct
  XPath) that must agree.
- Every graded value is confirmed to be printed on the rendered pages; the IRS stylesheets drop
  some data, so this is checked, not assumed.
- Generators pick only unambiguous cases: identities unique by name, city and state across all
  returns and the Business Master File; one original return for the year; no values on a rounding
  boundary. Difficulty is designed (non-December fiscal years, dense tables), never selected by
  which items a model fails.
- Every failure in the study was traced to its cause by comparing the submitted value with the return.

## Layout

| Module | Role |
| --- | --- |
| `fetch`, `corpus`, `facts` | Download IRS batches and the Business Master File; SQLite catalog and fact tables |
| `render`, `pages` | XML to page images with the IRS stylesheets; table of contents; page fidelity variants |
| `assignments`, `crosscheck`, `visibility` | Assignment generators and grader; independent recomputation; visibility check |
| `sandbox`, `agent`, `run` | Docker workstation, tool loop (OpenAI-compatible), runner |
| `study`, `analysis` | Reliability study dials, runs, intervals and failure taxonomy |
| `probes` | The single-value reading test |

## Running

Requires Docker, `uv`, about 15 GB of disk, and an Ollama cloud key in `OLLAMA_API_KEY`.

```sh
uv run python -m bench990.fetch                                  # IRS XML batches, indexes, BMF
uv run python -c "from bench990 import corpus, fetch; corpus.build(fetch.batches([2024, 2025, 2026]))"
uv run python -m bench990.facts
uv run playwright install chromium
docker build -t bench990-sandbox sandbox

uv run python -m bench990.study plan                             # validated study assignments
uv run python -m bench990.study run --model ollama/deepseek-v4.1-flash:1017
uv run python -m bench990.analysis                               # docs/study-results.md and chart
uv run python -m bench990.probes build && uv run python -m bench990.probes run --model ollama/deepseek-v4.1-flash:1017
```

Runs stopped by the provider (quota or server errors) are excluded from scores and resumable.

## Documents

- [docs/report.md](docs/report.md): the study.
- [docs/example.md](docs/example.md): one real run, step by step, and the digit it got wrong.
- [docs/rendering.md](docs/rendering.md): rendering returns to page images, and the stylesheets' limits.
- [docs/prior-art.md](docs/prior-art.md): related benchmarks and data access.
- [docs/appendix.md](docs/appendix.md): earlier rounds and the other assignment types.

## License

MIT. IRS data is public; the IRS stylesheets are downloaded at build time and not redistributed here.
