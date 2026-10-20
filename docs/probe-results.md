| Model | Probes | Condition | Read correctly (95% CI) | Part VII | Schedule J | Schedule I | Mean prompt tokens |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ollama_deepseek-v4.1-flash-1017 | 193 | page150 | 191/193 = 99.0% (96.3%–99.7%) | 71/72 | 39/39 | 81/82 | 1,075 |
| ollama_deepseek-v4.1-flash-1017 | 193 | page300 | 193/193 = 100.0% (98.0%–100.0%) | 72/72 | 39/39 | 82/82 | 1,075 |
| ollama_deepseek-v4.1-flash-1017 | 193 | strip300 | 192/193 = 99.5% (97.1%–99.9%) | 71/72 | 39/39 | 82/82 | 677 |

| Model | Comparison | Right only in first | Right only in second | Exact McNemar p |
| --- | --- | --- | --- | --- |
| ollama_deepseek-v4.1-flash-1017 | page150 vs strip300 | 1 | 2 | 1 |
| ollama_deepseek-v4.1-flash-1017 | page150 vs page300 | 0 | 2 | 0.5 |
