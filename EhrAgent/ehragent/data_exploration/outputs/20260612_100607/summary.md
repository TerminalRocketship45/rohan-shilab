# Data Exploration -- 6-Condition EHR Benchmark

**Date:** 2026-06-12 10:25:44
**Questions:** 5

---

## Accuracy vs Ground Truth

| Condition | Correct | Wrong | Incompleted | Accuracy | Completion Rate |
|-----------|---------|-------|-------------|----------|-----------------|
| CA + No Schema | 1 | 2 | 2 | 20.0% | 60.0% |
| CA + Dataset Schema | 1 | 2 | 2 | 20.0% | 60.0% |
| BL + No Schema | 1 | 4 | 0 | 20.0% | 100.0% |
| BL + Dataset Schema | 1 | 4 | 0 | 20.0% | 100.0% |

---

## Per-Question Status

| # | Question | CA + No Schema | CA + Dataset Schema | CA + ReFoRCE Schema | BL + No Schema | BL + Dataset Schema | BL + ReFoRCE Schema |
|---|----------|---------|---------|---------|---------|---------|---------|
| 1 | has patient 9474 received any diagnosis since... | OK (1t) | OK (1t) | -- | OK (1t) | OK (1t) | -- |
| 2 | what are the top four frequently prescribed d... | WRONG (5t) | WRONG (1t) | -- | WRONG (4t) | WRONG (7t) | -- |
| 3 | count the number of patients who were dead af... | INC (0t) | WRONG (1t) | -- | WRONG (1t) | WRONG (3t) | -- |
| 4 | count the number of patients who stayed in ca... | WRONG (1t) | INC (0t) | -- | WRONG (1t) | WRONG (4t) | -- |
| 5 | what are the top three frequent prescribed dr... | INC (0t) | INC (0t) | -- | WRONG (1t) | WRONG (3t) | -- |