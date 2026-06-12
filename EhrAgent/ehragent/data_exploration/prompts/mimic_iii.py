# EhrAgent/ehragent/data_exploration/prompts/mimic_iii.py
"""
Schema-parameterized prompt templates for MIMIC-III.

All builder functions accept schema_str:
  ""                    -> no schema (conditions A/D)
  DATASET_SCHEMA_*      -> dataset schema (conditions B/E)
  <explorer output>     -> ReFoRCE schema (conditions C/F)
"""

DATASET_SCHEMA_NARRATIVE = (
    "(1) Tables are linked by identifiers which usually have the suffix 'ID'. "
    "For example, SUBJECT_ID refers to a unique patient, HADM_ID refers to a unique "
    "admission to the hospital, and ICUSTAY_ID refers to a unique admission to an "
    "intensive care unit.\n"
    "(2) Charted events such as notes, laboratory tests, and fluid balance are stored "
    "in a series of 'events' tables. For example the outputevents table contains all "
    "measurements related to output for a given patient, while the labevents table "
    "contains laboratory test results for a patient.\n"
    "(3) Tables prefixed with 'd_' are dictionary tables and provide definitions for "
    "identifiers. For example, every row of chartevents is associated with a single "
    "ITEMID which represents the concept measured, but it does not contain the actual "
    "name of the measurement. By joining chartevents and d_items on ITEMID, it is "
    "possible to identify the concept represented by a given ITEMID.\n"
    "(4) For the databases, four of them are used to define and track patient stays: "
    "admissions, patients, icustays, and transfers. Another four tables are dictionaries "
    "for cross-referencing codes against their respective definitions: d_icd_diagnoses, "
    "d_icd_procedures, d_items, and d_labitems. The remaining tables, including "
    "chartevents, cost, inputevents_cv, labevents, microbiologyevents, outputevents, "
    "prescriptions, procedures_icd, contain data associated with patient care, such as "
    "physiological measurements, caregiver observations, and billing information."
)

DATASET_SCHEMA_COLUMNS = (
    "- admissions: ROW_ID, SUBJECT_ID, HADM_ID, ADMITTIME, DISCHTIME, ADMISSION_TYPE, "
    "ADMISSION_LOCATION, DISCHARGE_LOCATION, INSURANCE, LANGUAGE, MARITAL_STATUS, ETHNICITY, AGE\n"
    "- chartevents: ROW_ID, SUBJECT_ID, HADM_ID, ICUSTAY_ID, ITEMID, CHARTTIME, VALUENUM, VALUEUOM\n"
    "- cost: ROW_ID, SUBJECT_ID, HADM_ID, EVENT_TYPE, EVENT_ID, CHARGETIME, COST\n"
    "- d_icd_diagnoses: ROW_ID, ICD9_CODE, SHORT_TITLE, LONG_TITLE\n"
    "- d_icd_procedures: ROW_ID, ICD9_CODE, SHORT_TITLE, LONG_TITLE\n"
    "- d_items: ROW_ID, ITEMID, LABEL, LINKSTO\n"
    "- d_labitems: ROW_ID, ITEMID, LABEL\n"
    "- diagnoses_icd: ROW_ID, SUBJECT_ID, HADM_ID, ICD9_CODE, CHARTTIME\n"
    "- icustays: ROW_ID, SUBJECT_ID, HADM_ID, ICUSTAY_ID, FIRST_CAREUNIT, LAST_CAREUNIT, "
    "FIRST_WARDID, LAST_WARDID, INTIME, OUTTIME\n"
    "- inputevents_cv: ROW_ID, SUBJECT_ID, HADM_ID, ICUSTAY_ID, CHARTTIME, ITEMID, AMOUNT\n"
    "- labevents: ROW_ID, SUBJECT_ID, HADM_ID, ITEMID, CHARTTIME, VALUENUM, VALUEUOM\n"
    "- microbiologyevents: ROW_ID, SUBJECT_ID, HADM_ID, CHARTTIME, SPEC_TYPE_DESC, ORG_NAME\n"
    "- outputevents: ROW_ID, SUBJECT_ID, HADM_ID, ICUSTAY_ID, CHARTTIME, ITEMID, VALUE\n"
    "- patients: ROW_ID, SUBJECT_ID, GENDER, DOB, DOD\n"
    "- prescriptions: ROW_ID, SUBJECT_ID, HADM_ID, STARTDATE, ENDDATE, DRUG, "
    "DOSE_VAL_RX, DOSE_UNIT_RX, ROUTE\n"
    "- procedures_icd: ROW_ID, SUBJECT_ID, HADM_ID, ICD9_CODE, CHARTTIME\n"
    "- transfers: ROW_ID, SUBJECT_ID, HADM_ID, ICUSTAY_ID, EVENTTYPE, CAREUNIT, WARDID, INTIME, OUTTIME"
)

_LOADDB_TABLES = (
    "admissions, chartevents, cost, d_icd_diagnoses, d_icd_procedures, d_items, "
    "d_labitems, diagnoses_icd, icustays, inputevents_cv, labevents, "
    "microbiologyevents, outputevents, patients, prescriptions, procedures_icd, transfers"
)

_CODING_TEMPLATE = """{schema_preamble}Write a python code to solve the given question. You can use the following functions:
(1) Calculate(FORMULA), which calculates the FORMULA and returns the result.
(2) LoadDB(DBNAME) which loads the database DBNAME and returns the database. The DBNAME can be one of the following: {table_list}.
(3) FilterDB(DATABASE, CONDITIONS), which filters the DATABASE according to the CONDITIONS and returns the filtered database. The CONDITIONS is a string composed of multiple conditions, each of which consists of the column_name, the relation and the value (e.g., COST<10). The CONDITIONS is one single string (e.g., "admissions, SUBJECT_ID=24971").
(4) GetValue(DATABASE, ARGUMENT), which returns a string containing all the values of the column in the DATABASE (if multiple values, separated by ", "). When there is no additional operations on the values, the ARGUMENT is the column_name in demand. If the values need to be returned with certain operations, the ARGUMENT is composed of the column_name and the operation (like COST, sum). Please do not contain " or ' in the argument.
(5) SQLInterpreter(SQL), which interprets the query SQL and returns the result.
(6) Calendar(DURATION), which returns the date after the duration of time.
Use the variable 'answer' to store the answer of the code. Here are some examples:
{examples}
(END OF EXAMPLES)
Knowledge:
{knowledge}
Question: {question}
Solution: """

_COMPILER_BASE = """You are a code execution simulator for an EHR query system.
You receive Python code that uses EHR API functions and simulate what would happen if executed.
You know the full table and column schema but have NO access to actual patient data.
{schema_section}
Check for:
- Wrong table names passed to LoadDB()
- Wrong column names passed to FilterDB() or GetValue()
- Wrong argument format for any API function
- SQL syntax or schema errors in SQLInterpreter()
- Any other obvious code errors

Always respond with EXACTLY [SUCCESS] or [ERROR] on the first line, followed by your
simulated result (SUCCESS) or the predicted error message (ERROR)."""

CompilerAgent_FewShot_Examples = """--- Example 1: Correct API code -> SUCCESS ---
Question: had any tpn w/lipids been given to patient 2238 in their last hospital visit?
Code:
patient_db = LoadDB('admissions')
filtered_patient_db = FilterDB(patient_db, 'SUBJECT_ID=2238||min(DISCHTIME)')
hadm_id = GetValue(filtered_patient_db, 'HADM_ID')
d_items_db = LoadDB('d_items')
filtered_d_items_db = FilterDB(d_items_db, 'LABEL=tpn w/lipids')
item_id = GetValue(filtered_d_items_db, 'ITEMID')
icustays_db = LoadDB('icustays')
filtered_icustays_db = FilterDB(icustays_db, 'HADM_ID={}'.format(hadm_id))
icustay_id = GetValue(filtered_icustays_db, 'ICUSTAY_ID')
inputevents_cv_db = LoadDB('inputevents_cv')
filtered_inputevents_cv_db = FilterDB(inputevents_cv_db, 'HADM_ID={}||ICUSTAY_ID={}||ITEMID={}'.format(hadm_id, icustay_id, item_id))
if len(filtered_inputevents_cv_db) > 0:
    answer = 1
else:
    answer = 0

[SUCCESS]
1

--- Example 2: Correct API code -> SUCCESS ---
Question: calculate the length of stay of the first stay of patient 27392 in the icu.
Code:
from datetime import datetime
patient_db = LoadDB('admissions')
filtered_patient_db = FilterDB(patient_db, 'SUBJECT_ID=27392||min(ADMITTIME)')
hadm_id = GetValue(filtered_patient_db, 'HADM_ID')
icustays_db = LoadDB('icustays')
filtered_icustays_db = FilterDB(icustays_db, 'HADM_ID={}'.format(hadm_id))
intime = GetValue(filtered_icustays_db, 'INTIME')
outtime = GetValue(filtered_icustays_db, 'OUTTIME')
intime = datetime.strptime(intime, '%Y-%m-%d %H:%M:%S')
outtime = datetime.strptime(outtime, '%Y-%m-%d %H:%M:%S')
length_of_stay = outtime - intime
if length_of_stay.seconds // 3600 > 12:
    answer = length_of_stay.days + 1
else:
    answer = length_of_stay.days

[SUCCESS]
3

--- Example 3: Invalid FilterDB separator -> ERROR ---
Question: count patients in their 30s prescribed metformin.
Code:
patients_db = LoadDB('patients')
filtered_patients_db = FilterDB(patients_db, 'YEAR(DOB) >= 1984 && YEAR(DOB) <= 1993')
subject_id_list = GetValue(filtered_patients_db, 'SUBJECT_ID, list')

[ERROR]
Error: The filtering query YEAR(DOB) >= 1984 && YEAR(DOB) <= 1993 is incorrect. FilterDB only supports '||' to join conditions, not '&&'. SQL functions like YEAR() are also not supported.

--- Example 4: SQL subquery inside FilterDB -> ERROR ---
Question: how many days since patient 55501 was first prescribed penicillin?
Code:
prescriptions_db = LoadDB('prescriptions')
filtered_prescriptions_db = FilterDB(prescriptions_db, 'SUBJECT_ID=55501||ITEMID=(SELECT ITEMID FROM d_items WHERE LABEL="penicillin")')

[ERROR]
Error: SQL subqueries are not supported inside FilterDB. Load the lookup table separately with LoadDB, retrieve the ITEMID with GetValue, then pass the value into FilterDB."""


def get_coding_agent_prompt(schema_str, examples, knowledge, question):
    if schema_str:
        schema_preamble = f"Assume you have knowledge of several tables:\n{schema_str}\n"
    else:
        schema_preamble = ""
    return _CODING_TEMPLATE.format(
        schema_preamble=schema_preamble,
        table_list=_LOADDB_TABLES,
        examples=examples,
        knowledge=knowledge,
        question=question,
    )


def get_compiler_system_message(schema_str):
    if schema_str:
        section = f"\nAvailable tables and columns (mimic_iii):\n{schema_str}\n"
    else:
        section = "\n(No schema provided — check API syntax and function argument format only, not column names.)\n"
    return _COMPILER_BASE.format(schema_section=section)


def get_compiler_debugger_system_message(schema_str):
    base = get_compiler_system_message(schema_str)
    return base + '\n\nIf you find an error, also provide a suggested fix on a new line prefixed with:\n"Suggested fix: "'
