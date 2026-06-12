# EhrAgent/ehragent/data_exploration/prompts/eicu.py
"""Schema-parameterized prompt templates for eICU."""

DATASET_SCHEMA_NARRATIVE = (
    "(1) Data include vital signs, laboratory measurements, medications, APACHE components, "
    "care plan information, admission diagnosis, patient history, time-stamped diagnoses "
    "from a structured problem list, and similarly chosen treatments.\n"
    "(2) Data from each patient is collected into a common warehouse only if certain "
    "'interfaces' are available. Each interface is used to transform and load a certain "
    "type of data: vital sign interfaces incorporate vital signs, laboratory interfaces "
    "provide measurements on blood samples, and so on.\n"
    "(3) It is important to be aware that different care units may have different interfaces "
    "in place, and that the lack of an interface will result in no data being available for "
    "a given patient, even if those measurements were made in reality.\n"
    "(4) All the databases are used to record information associated to patient care, such as "
    "allergy, cost, diagnosis, intakeoutput, lab, medication, microlab, patient, treatment, "
    "vitalperiodic."
)

DATASET_SCHEMA_COLUMNS = (
    "- allergy: allergyid, patientunitstayid, drugname, allergyname, allergytime\n"
    "- cost: costid, uniquepid, patienthealthsystemstayid, eventtype, eventid, chargetime, cost\n"
    "- diagnosis: diagnosisid, patientunitstayid, icd9code, diagnosisname, diagnosistime\n"
    "- intakeoutput: intakeoutputid, patientunitstayid, cellpath, celllabel, cellvaluenumeric, intakeoutputtime\n"
    "- lab: labid, patientunitstayid, labname, labresult, labresulttime\n"
    "- medication: medicationid, patientunitstayid, drugname, dosage, routeadmin, drugstarttime, drugstoptime\n"
    "- microlab: microlabid, patientunitstayid, culturesite, organism, culturetakentime\n"
    "- patient: patientunitstayid, patienthealthsystemstayid, gender, age, ethnicity, "
    "hospitalid, wardid, admissionheight, hospitaladmitsource, hospitaldischargestatus, "
    "admissionweight, dischargeweight, uniquepid, hospitaladmittime, unitadmittime, "
    "unitdischargetime, hospitaldischargetime\n"
    "- treatment: treatmentid, patientunitstayid, treatmentname, treatmenttime\n"
    "- vitalperiodic: vitalperiodicid, patientunitstayid, temperature, sao2, heartrate, "
    "respiration, systemicsystolic, systemicdiastolic, systemicmean, observationtime"
)

_LOADDB_TABLES = (
    "allergy, cost, diagnosis, intakeoutput, lab, medication, microlab, "
    "patient, treatment, vitalperiodic"
)

_CODING_TEMPLATE = """{schema_preamble}Write a python code to solve the given question. You can use the following functions:
(1) Calculate(FORMULA), which calculates the FORMULA and returns the result.
(2) LoadDB(DBNAME) which loads the database DBNAME and returns the database. The DBNAME can be one of the following: {table_list}.
(3) FilterDB(DATABASE, CONDITIONS), which filters the DATABASE according to the CONDITIONS and returns the filtered database. The CONDITIONS is a string composed of multiple conditions, each of which consists of the column_name, the relation and the value (e.g., COST<10). The CONDITIONS is one single string (e.g., "admissions, SUBJECT_ID=24971"). Different conditions are separated by '||'.
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
Question: was the fluticasone-salmeterol 250-50 mcg/dose in aepb prescribed to patient 035-2205 on their current hospital encounter?
Code:
patient_db = LoadDB('patient')
filtered_patient_db = FilterDB(patient_db, 'uniquepid=035-2205||hospitaldischargetime=null')
patientunitstayid = GetValue(filtered_patient_db, 'patientunitstayid')
medication_db = LoadDB('medication')
filtered_medication_db = FilterDB(medication_db, 'patientunitstayid={}||drugname=fluticasone-salmeterol 250-50 mcg/dose in aepb'.format(patientunitstayid))
if len(filtered_medication_db) > 0:
    answer = 1
else:
    answer = 0

[SUCCESS]
1

--- Example 2: Correct API code -> SUCCESS ---
Question: what is the minimum hospital cost for a drug with a name called albumin 5% since 6 years ago?
Code:
date = Calendar('-6 year')
medication_db = LoadDB('medication')
filtered_medication_db = FilterDB(medication_db, 'drugname=albumin 5%')
patientunitstayid_list = GetValue(filtered_medication_db, 'patientunitstayid, list')
patient_db = LoadDB('patient')
filtered_patient_db = FilterDB(patient_db, 'patientunitstayid in {}'.format(patientunitstayid_list))
patienthealthsystemstayid_list = GetValue(filtered_patient_db, 'patienthealthsystemstayid, list')
cost_db = LoadDB('cost')
min_cost = 1e9
for patienthealthsystemstayid in patienthealthsystemstayid_list:
    filtered_cost_db = FilterDB(cost_db, 'patienthealthsystemstayid={}||chargetime>{}'.format(patienthealthsystemstayid, date))
    cost = GetValue(filtered_cost_db, 'cost, sum')
    if cost < min_cost:
        min_cost = cost
answer = min_cost

[SUCCESS]
245.89

--- Example 3: Wrong table name -> ERROR ---
Question: count patients with magnesium lab test this year.
Code:
lab_db = LoadDB('labs')
filtered_lab_db = FilterDB(lab_db, 'labname=magnesium')

[ERROR]
Error: 'labs' is not a valid table name. Valid tables are: allergy, cost, diagnosis, intakeoutput, lab, medication, microlab, patient, treatment, vitalperiodic. Use LoadDB('lab') instead."""


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
        section = f"\nAvailable tables and columns (eicu):\n{schema_str}\n"
    else:
        section = "\n(No schema provided — check API syntax and function argument format only, not column names.)\n"
    return _COMPILER_BASE.format(schema_section=section)


def get_compiler_debugger_system_message(schema_str):
    base = get_compiler_system_message(schema_str)
    return base + '\n\nIf you find an error, also provide a suggested fix on a new line prefixed with:\n"Suggested fix: "'
