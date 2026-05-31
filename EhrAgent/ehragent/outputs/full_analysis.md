# EHRAgent Pipeline Full Analysis

**Dataset:** mimic_iii | **n=30** | **seed=42** | **Model:** gpt-4o-mini

---

## Few-Shot Examples

### Coding Agent (EHRAgent_4Shots_Knowledge) — `prompts_mimic.py`

| # | Question |
|---|----------|
| 1 | What is the maximum total hospital cost that involves a diagnosis named comp-oth vasc dev/graft since 1 year ago? |
| 2 | Had any tpn w/lipids been given to patient 2238 in their last hospital visit? |
| 3 | What was the name of the procedure that was given two or more times to patient 58730? |
| 4 | Calculate the length of stay of the first stay of patient 27392 in the icu. |

### Compiler / Debugger Agent (CompilerAgent_FewShot_Examples) — `prompts_mimic.py`

| # | Question | Label |
|---|----------|-------|
| 1 | Had any tpn w/lipids been given to patient 2238 in their last hospital visit? | SUCCESS |
| 2 | Calculate the length of stay of the first stay of patient 27392 in the icu. | SUCCESS |
| 3 | **Count the number of patients who stayed in careunit ccu since 5 year ago.** | ERROR (`SUBJECT_ID, unique`) |
| 4 | **What was the total amount of dose of ranitidine that patient 24971 were prescribed in 01/2105?** | ERROR (`DRUG_NAME` wrong col) |

> ⚠️ **Contamination:** Examples 3 and 4 above appear verbatim in the 30 evaluated questions.
> The CCU question (shown as ERROR for `SUBJECT_ID, unique`) and the ranitidine question
> (shown as ERROR for `DRUG_NAME`) are in the evaluation set. Both are `wrong` in baseline.

---

## Per-Approach Summary Tables

### Baseline

| Metric | Value |
|--------|-------|
| Total questions | 30 |
| **Correct** | **15 (50.0%)** |
| Wrong | 15 |
| Incompleted (never ran) | 0 |
| Completion rate (ran at all) | 100.0% |
| Hit max tries (≥11) | 11 |

### Compiler Agent

| Metric | Value |
|--------|-------|
| Total questions | 30 |
| **Correct** | **10 (33.3%)** |
| Wrong | 17 |
| Incompleted (never ran) | 3 |
| Completion rate (ran at all) | 90.0% |
| Hit max tries (≥11) | 27 |

### New Debugger

| Metric | Value |
|--------|-------|
| Total questions | 30 |
| **Correct** | **8 (26.7%)** |
| Wrong | 20 |
| Incompleted (never ran) | 2 |
| Completion rate (ran at all) | 93.3% |
| Hit max tries (≥11) | 28 |

## Approach Comparison

| Metric | Baseline | Compiler Agent | New Debugger |
|--------|----------|----------------|--------------|
| Correct | 15 (50.0%) | 10 (33.3%) | 8 (26.7%) |
| Wrong | 15 | 17 | 20 |
| Incompleted | 0 | 3 | 2 |
| Completion rate | 100.0% | 90.0% | 93.3% |
| Hit max tries (≥11) | 11 | 27 | 28 |

---

## Compiler Agent vs Baseline — What Changed?

| Direction | Count |
|-----------|-------|
| ✅ Wrong → Correct (gains) | 0 |
| ❌ Correct → Wrong (regressions) | 5 |
| ⚠️ Correct → Incompleted | 0 |
| — Wrong → Incompleted | 3 |
| Net correct change | -5 |

**Regressions (correct → wrong):**

- `count the number of patients who were dead after having been diagnosed w…`
- `what was the name of the specimen that patient 40707 was last tested on …`
- `when was the last time that patient 48868 was diagnosed with ac salpingo…`
- `what does periph t cell lym abdom stand for?`
- `what was the total amount of dose of pioglitazone that patient 16992 wer…`

## New Debugger vs Baseline — What Changed?

| Direction | Count |
|-----------|-------|
| ✅ Wrong → Correct (gains) | 0 |
| ❌ Correct → Wrong (regressions) | 6 |
| ⚠️ Correct → Incompleted | 1 |
| — Wrong → Incompleted | 1 |
| Net correct change | -7 |

**Regressions (correct → wrong):**

- `count the number of patients who were dead after having been diagnosed w…`
- `what was the name of the specimen that patient 40707 was last tested on …`
- `when was the last time that patient 48868 was diagnosed with ac salpingo…`
- `count the number of patients who were admitted to the hospital until 3 y…`
- `what does periph t cell lym abdom stand for?`
- `what was the total amount of dose of pioglitazone that patient 16992 wer…`

**Correct → Incompleted:**

- `has patient 9474 received any diagnosis since 1 year ago?`

---

## Per-Question Status (all 30)

| # | Question (truncated) | Baseline | Compiler Agent | New Debugger |
|---|----------------------|----------|----------------|--------------|
| 1 | has patient 9474 received any diagnosis since 1 year ag… | ✅ correct (1t) | ✅ correct (11t) | ⚠️ incompleted (0t) |
| 2 | what are the top four frequently prescribed drugs that … | ❌ wrong (2t) | ❌ wrong (11t) | ❌ wrong (11t) |
| 3 | count the number of patients who were dead after having… | ✅ correct (5t) | ❌ wrong (11t) | ❌ wrong (11t) |
| 4 | count the number of patients who stayed in careunit ccu… | ❌ wrong (2t) | ❌ wrong (11t) | ❌ wrong (11t) |
| 5 | what are the top three frequent prescribed drugs for pa… | ❌ wrong (11t) | ❌ wrong (11t) | ❌ wrong (11t) |
| 6 | count the number of drugs patient 26777 were prescribed… | ✅ correct (1t) | ✅ correct (11t) | ✅ correct (11t) |
| 7 | what was the name of the specimen that patient 40707 wa… | ✅ correct (2t) | ❌ wrong (11t) | ❌ wrong (11t) |
| 8 | when was the first time that patient 30296 was diagnose… | ❌ wrong (5t) | ❌ wrong (11t) | ❌ wrong (11t) |
| 9 | how many hours have passed since patient 90663 was admi… | ❌ wrong (11t) | ❌ wrong (11t) | ❌ wrong (11t) |
| 10 | has patient 83466 received a excise lg intestine les pr… | ✅ correct (1t) | ✅ correct (11t) | ✅ correct (11t) |
| 11 | what is the difference between the total volume of inta… | ❌ wrong (1t) | ❌ wrong (11t) | ❌ wrong (11t) |
| 12 | count the number of patients who were prescribed hepari… | ✅ correct (1t) | ✅ correct (11t) | ✅ correct (11t) |
| 13 | count the number of patients who received a int inser l… | ✅ correct (1t) | ✅ correct (11t) | ✅ correct (11t) |
| 14 | count the number of times that patient 14035 received a… | ✅ correct (11t) | ✅ correct (11t) | ✅ correct (11t) |
| 15 | how many hours have passed since the first time patient… | ❌ wrong (11t) | ❌ wrong (11t) | ❌ wrong (11t) |
| 16 | when was the last time that patient 48868 was diagnosed… | ✅ correct (11t) | ❌ wrong (11t) | ❌ wrong (11t) |
| 17 | has patient 67418 been prescribed any medication until … | ✅ correct (1t) | ✅ correct (11t) | ✅ correct (11t) |
| 18 | how many days have passed since the first time patient … | ❌ wrong (11t) | ⚠️ incompleted (0t) | ⚠️ incompleted (0t) |
| 19 | what was the total amount of dose of ranitidine that pa… | ❌ wrong (11t) | ❌ wrong (11t) | ❌ wrong (11t) |
| 20 | count the number of times that patient 28447 received a… | ✅ correct (11t) | ✅ correct (11t) | ✅ correct (11t) |
| 21 | what were the top three frequent diagnoses of patients … | ❌ wrong (1t) | ⚠️ incompleted (0t) | ❌ wrong (11t) |
| 22 | what are the top five frequent drugs that patients were… | ❌ wrong (1t) | ❌ wrong (11t) | ❌ wrong (11t) |
| 23 | what are the top four frequently prescribed drugs that … | ❌ wrong (11t) | ❌ wrong (11t) | ❌ wrong (11t) |
| 24 | has patient 10425 received any lab test since 6 year ag… | ✅ correct (1t) | ✅ correct (11t) | ✅ correct (11t) |
| 25 | count the number of patients who were admitted to the h… | ✅ correct (1t) | ✅ correct (11t) | ❌ wrong (11t) |
| 26 | what does periph t cell lym abdom stand for? | ✅ correct (1t) | ❌ wrong (11t) | ❌ wrong (11t) |
| 27 | how many hours have passed since the last time patient … | ❌ wrong (4t) | ❌ wrong (11t) | ❌ wrong (11t) |
| 28 | what was the name of the output that patient 655 first … | ❌ wrong (11t) | ⚠️ incompleted (0t) | ❌ wrong (11t) |
| 29 | what are the top three frequent procedures of patients … | ❌ wrong (11t) | ❌ wrong (11t) | ❌ wrong (11t) |
| 30 | what was the total amount of dose of pioglitazone that … | ✅ correct (1t) | ❌ wrong (11t) | ❌ wrong (11t) |

---
