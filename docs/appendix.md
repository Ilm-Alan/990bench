# Appendix: earlier rounds

How the benchmark got to its final form, newest first. Each row is one run of one assignment.
Runs stopped by the provider (quota) are excluded. These rounds use assignment types the final
study does not: follow the money, compensation ranking, grant ledger and Schedule J table.

## Round 4, 2026-10-20: dense-table transcription (document mode)

Two new kinds ask for whole tables copied from page images and graded as an exact multiset of
rows: every Schedule I, Part II row of several funders (grant ledger), and row (i) of every
Schedule J, Part II entry across a peer group (columns B(i)–D). Both agree with the
independent recomputation and pass the visibility check.

| Model | Assignment | Result | Page views | Tool calls | Prompt tokens |
| --- | --- | --- | --- | --- | --- |
| deepseek-v4.1-flash:1017 | Grant ledger, 4 funders, 196 rows | Pass (196/196) | 33 | 53 | 767,701 |
| deepseek-v4.1-flash:1017 | Schedule J table, 8 returns, 65 rows × 5 amounts | Pass (65/65) | 31 | 49 | 866,314 |

Transcription from clean renders is reliable even for a cheap model.

## Round 3, 2026-10-20: fiscal-year traps and dense pages (document mode)

Redesigned assignments ask for each organization's return by tax year, with at least half the
organizations having a live fiscal-year trap (a non-December fiscal year whose previous return
also ends in the requested year). Values come from Part IX columns, Part VII, Schedule I
continuation tables and Schedule J rows (i) and (ii). All six generated assignments agree with
the independent recomputation and pass the visibility check.

| Model | Assignment | Result | Tool calls | Prompt tokens |
| --- | --- | --- | --- | --- |
| deepseek-v4.1-flash:1017 | Due diligence, 20 applicants, 11 traps | Pass (120/120 values) | 121 (72 page views) | 2,591,987 |
| deepseek-v4.1-flash:1017 | Follow the money, 16 recipients, 9 traps | Pass | 51 | 916,701 |
| deepseek-v4.1-flash:1017 | Compensation, 12 returns, 8 traps | Pass | 73 | 1,105,661 |

The model located organizations through the Business Master File, mapped tax years to tax
periods correctly, opened each return's table of contents and read the needed pages.

## Round 2, 2026-10-19: first long assignments

| Mode | Model | Assignments | Passed |
| --- | --- | --- | --- |
| Data (XML + bash) | kimi-k3, glm-5.3, deepseek-v4.1-flash | 15 | 14 |
| Documents | deepseek-v4.1-flash:1017 | 3 | 2 |

- In data mode, models write one XML parser and get every value right.
- The two failures (one per mode, same model, same assignment) missed one grant recipient
  whose fiscal year ends in September: its tax-year-2024 return has tax period 202509, and the
  model filtered the index on 2024. The return's first page states the tax year, so the failure
  is the model's. In data mode the same recipient was also the one stored in a split zip.

## Round 1, 2026-10-19: spike

18 single-question tasks (lookups, two-year change, top-paid person, one-hop grant chain, city
ranking, unanswerable year) over two IRS batches, with flattened XML fields as the read tool:
gpt-oss:120b, kimi-k3, glm-5.3 and deepseek-v4.1-flash each scored 18/18.

## Data quality

Over all 948,853 Form 990s released 2024–2026: amended and duplicate returns exist and are
excluded from ground truth; Part I and Part VIII revenue totals disagree on about 1 return in
8,000 (spike sample); the IRS index labels both halves of split batches with one zip name and
three zips use Deflate64 (both documented for agents).

## Conclusion to date

Retrieval-and-transcription assignments, even long ones with traps over page images, are within
reach of a cheap current model. Length raises cost (2.6M prompt tokens for one assignment) more
than failure rate. Harder assignments need a different source of difficulty.
