# EHRAgent Pipeline Analysis

**Run directory:** `C:\Users\rohan\Downloads\ML\ShiLab\EhrAgent\ehragent\outputs\20260530_201842`
**n = 10 questions**

---

## Accuracy vs Ground Truth

| Metric | Baseline | Compiler Agent | New Debugger |
|--------|----------|----------------|--------------|
| Correct | 4 / 10 (40.0%) | 3 / 10 (30.0%) | 3 / 10 (30.0%) |
| Wrong | 5 | 7 | 7 |
| Incompleted | 1 | 0 | 0 |
|   — compiler false positive | 0 | 3 | 3 |
|   — exception | 0 | 1 | 0 |
| Completion rate | 90.0% | 100.0% | 100.0% |
| Hit max (11 tries) | 1 | 0 | 0 |

---

## Agreement with Baseline Answer

> Matching rules: both correct = match; both wrong with same value = match;
> both incompleted with same reason = match.

| Approach | Matched | Total | Agreement % |
|----------|---------|-------|-------------|
| Baseline | — | — | 100% (reference) |
| Compiler Agent | 6 | 10 | 60.0% |
| New Debugger | 5 | 10 | 50.0% |

---

## Per-Question Status

| # | Question | Baseline | Compiler Agent | CA=BL? | New Debugger | ND=BL? |
|---|----------|----------|----------------|--------|--------------|--------|
| 1 | has patient 9474 received any diagnosis since 1 year ag... | CORRECT (4t) | CORRECT (4t) | YES | CORRECT (2t) | YES |
| 2 | what are the top four frequently prescribed drugs that ... | WRONG (1t) | WRONG (2t) | NO | WRONG (1t) | YES |
| 3 | count the number of patients who were dead after having... | WRONG (1t) | WRONG (0t) | YES | WRONG (1t) | YES |
| 4 | count the number of patients who stayed in careunit ccu... | INCOMP (11t) | WRONG (0t) | NO | WRONG (7t) | NO |
| 5 | what are the top three frequent prescribed drugs for pa... | WRONG (2t) | WRONG (2t) | YES | WRONG (0t) | YES |
| 6 | count the number of drugs patient 26777 were prescribed... | CORRECT (2t) | CORRECT (1t) | YES | WRONG (0t) | NO |
| 7 | what was the name of the specimen that patient 40707 wa... | CORRECT (1t) | CORRECT (2t) | YES | CORRECT (1t) | YES |
| 8 | when was the first time that patient 30296 was diagnose... | CORRECT (4t) | WRONG (0t) | NO | WRONG (0t) | NO |
| 9 | how many hours have passed since patient 90663 was admi... | WRONG (1t) | WRONG (4t) | NO | WRONG (3t) | NO |
| 10 | has patient 83466 received a excise lg intestine les pr... | WRONG (1t) | WRONG (0t) | YES | CORRECT (1t) | NO |

---

## Compiler Agent vs Baseline -- Flips

| Change | Count |
|--------|-------|
| Gains (wrong -> correct) | 0 |
| Regressions (correct -> wrong) | 1 |
| Correct -> Incompleted | 0 |
| Net | -1 |

**Regressions:**
- when was the first time that patient 30296 was diagnosed with liver tr

## New Debugger vs Baseline -- Flips

| Change | Count |
|--------|-------|
| Gains (wrong -> correct) | 1 |
| Regressions (correct -> wrong) | 2 |
| Correct -> Incompleted | 0 |
| Net | -1 |

**Gains:**
- has patient 83466 received a excise lg intestine les procedure last ye

**Regressions:**
- count the number of drugs patient 26777 were prescribed until 109 mont
- when was the first time that patient 30296 was diagnosed with liver tr

---

## Error Breakdown (wrong + incompleted only)

| Category | Baseline | Compiler Agent | New Debugger |
|----------|----------|----------------|--------------|
| Compiler false positive (silenced) | 0 | 3 | 3 |
| Wrong column name | 1 | 1 | 0 |
| Invalid separator (&&/AND) | 0 | 0 | 0 |
| SQL subquery in FilterDB | 0 | 0 | 0 |
| Hit max tries | 1 | 0 | 0 |
| No error info | 4 | 0 | 2 |
| Other | 0 | 3 | 2 |