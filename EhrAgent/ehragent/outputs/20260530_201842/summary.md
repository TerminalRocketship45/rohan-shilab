# EHRAgent Pipeline Analysis

**Date:** 2026-05-30 21:11:07
**Dataset:** mimic_iii | **n=10** | **Model:** varies per run

---

## Summary Table

| Metric | Baseline | Compiler Agent | New Debugger |
|--------|----------|----------------|--------------|
| Correct | 4 (40.0%) | 3 (30.0%) | 3 (30.0%) |
| Wrong | 6 | 3 | 4 |
| Incompleted | 0 | 4 | 3 |
| Completion rate | 100.0% | 60.0% | 70.0% |
| Hit max (11t) | 1 | 0 | 0 |

---

## Per-Question Status

| # | Question | Baseline | Compiler Agent | New Debugger |
|---|----------|----------|----------------|--------------|
| 1 | has patient 9474 received any diagnosis since 1 year ag... | ✅ correct (4t) | ✅ correct (4t) | ✅ correct (2t) |
| 2 | what are the top four frequently prescribed drugs that ... | ❌ wrong (1t) | ❌ wrong (2t) | ❌ wrong (1t) |
| 3 | count the number of patients who were dead after having... | ❌ wrong (1t) | ⚠️ incompleted (0t) | ❌ wrong (1t) |
| 4 | count the number of patients who stayed in careunit ccu... | ❌ wrong (11t) | ⚠️ incompleted (0t) | ❌ wrong (7t) |
| 5 | what are the top three frequent prescribed drugs for pa... | ❌ wrong (2t) | ❌ wrong (2t) | ⚠️ incompleted (0t) |
| 6 | count the number of drugs patient 26777 were prescribed... | ✅ correct (2t) | ✅ correct (1t) | ⚠️ incompleted (0t) |
| 7 | what was the name of the specimen that patient 40707 wa... | ✅ correct (1t) | ✅ correct (2t) | ✅ correct (1t) |
| 8 | when was the first time that patient 30296 was diagnose... | ✅ correct (4t) | ⚠️ incompleted (0t) | ⚠️ incompleted (0t) |
| 9 | how many hours have passed since patient 90663 was admi... | ❌ wrong (1t) | ❌ wrong (4t) | ❌ wrong (3t) |
| 10 | has patient 83466 received a excise lg intestine les pr... | ❌ wrong (1t) | ⚠️ incompleted (0t) | ✅ correct (1t) |

---

## Compiler Agent vs Baseline

| Change | Count |
|--------|-------|
| Gains (wrong -> correct) | 0 |
| Regressions (correct -> wrong) | 0 |
| Correct -> Incompleted | 1 |
| Net | -1 |

## New Debugger vs Baseline

| Change | Count |
|--------|-------|
| Gains (wrong -> correct) | 1 |
| Regressions (correct -> wrong) | 0 |
| Correct -> Incompleted | 2 |
| Net | -1 |

**Gains:**
- has patient 83466 received a excise lg intestine les procedure last ye
