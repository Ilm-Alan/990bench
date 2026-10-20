| Model | Cell | Runs | Passed | Wrong values | Stopped by budget | Pass rate (95% CI) | Value accuracy, finished runs | Mean tool calls | Mean prompt tokens | Prompt tokens per correct deliverable |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| deepseek-v4.1-flash:1017 | n10-t50-clean | 4 | 3 | 1 | 0 | 3/4 (30%–95%) | 99.6% | 106 | 2,357,268 | 3,143,024 |
| deepseek-v4.1-flash:1017 | n5-t50-clean | 4 | 2 | 0 | 2 | 2/4 (15%–85%) | 100.0% | 82 | 1,565,516 | 3,131,032 |
| deepseek-v4.1-flash:1017 | n20-t50-clean | 4 | 2 | 2 | 0 | 2/4 (15%–85%) | 99.6% | 187 | 3,608,225 | 7,216,450 |
| deepseek-v4.1-flash:1017 | n40-t50-clean | 4 | 2 | 2 | 0 | 2/4 (15%–85%) | 99.8% | 254 | 5,620,271 | 11,240,542 |
| deepseek-v4.1-flash:1017 | n10-t0-clean | 4 | 2 | 1 | 1 | 2/4 (15%–85%) | 99.4% | 110 | 2,696,584 | 5,393,168 |
| deepseek-v4.1-flash:1017 | n10-t100-clean | 4 | 3 | 1 | 0 | 3/4 (30%–95%) | 99.6% | 108 | 2,609,961 | 3,479,948 |
| deepseek-v4.1-flash:1017 | n10-t50-bilevel | 4 | 2 | 0 | 2 | 2/4 (15%–85%) | 100.0% | 168 | 3,284,597 | 6,569,194 |
| deepseek-v4.1-flash:1017 | n10-t50-coarse | 4 | 0 | 0 | 4 | 0/4 (0%–49%) | n/a | 98 | 4,033,270 | n/a |
| gemma4:31b | n10-t50-clean | 4 | 0 | 2 | 2 | 0/4 (0%–49%) | 65.9% | 134 | 2,864,639 | n/a |

Errors in finished runs, one label per wrong applicant:

| Model | Error | Wrong applicants |
| --- | --- | --- |
| deepseek-v4.1-flash:1017 | top_comp: misread digits | 3 |
| deepseek-v4.1-flash:1017 | total_revenue: wrong line or value | 2 |
| deepseek-v4.1-flash:1017 | total_revenue: misread digits | 1 |
| deepseek-v4.1-flash:1017 | Schedule L judged wrong | 1 |
| gemma4:31b | total_revenue: wrong line or value | 14 |
| gemma4:31b | program share wrong | 2 |
| gemma4:31b | wrong return (tax year mapped to the wrong period) | 1 |
| gemma4:31b | top_comp: wrong line or value | 1 |
| gemma4:31b | total_revenue: misread digits | 1 |
