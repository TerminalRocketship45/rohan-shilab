# Data Exploration -- 6-Condition EHR Benchmark

**Date:** 2026-06-12 14:29:38
**Questions:** 5

---

## Accuracy vs Ground Truth

| Condition | Correct | Wrong | Incompleted | Accuracy | Completion Rate |
|-----------|---------|-------|-------------|----------|-----------------|
| CA + No Schema | 1 | 1 | 3 | 20.0% | 40.0% |
| CA + Dataset Schema | 1 | 3 | 1 | 20.0% | 80.0% |
| BL + No Schema | 2 | 3 | 0 | 40.0% | 100.0% |
| BL + Dataset Schema | 2 | 3 | 0 | 40.0% | 100.0% |

---

## Per-Question Status

| # | Question | CA + No Schema | CA + Dataset Schema | CA + ReFoRCE Schema | BL + No Schema | BL + Dataset Schema | BL + ReFoRCE Schema |
|---|----------|---------|---------|---------|---------|---------|---------|
| 1 | has patient 9474 received any diagnosis since... | OK (11t) | OK (11t) | -- | OK (11t) | OK (11t) | -- |
| 2 | what are the top four frequently prescribed d... | WRONG (11t) | WRONG (10t) | -- | WRONG (11t) | WRONG (11t) | -- |
| 3 | count the number of patients who were dead af... | INC (0t) | WRONG (10t) | -- | WRONG (11t) | WRONG (11t) | -- |
| 4 | count the number of patients who stayed in ca... | INC (0t) | WRONG (11t) | -- | OK (11t) | OK (11t) | -- |
| 5 | what are the top three frequent prescribed dr... | INC (0t) | INC (0t) | -- | WRONG (11t) | WRONG (11t) | -- |