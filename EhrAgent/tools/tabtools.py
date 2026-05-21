import os
import pandas as pd
import json
import re
import sqlite3
import Levenshtein

_DATASET_PATH = None
_DATASET = None


def configure(dataset_path, dataset):
    global _DATASET_PATH, _DATASET
    _DATASET_PATH = dataset_path
    _DATASET = dataset


def _mimic_ehr_dict():
    base = os.path.join(_DATASET_PATH, "mimic_iii")
    return {
        "admissions":       os.path.join(base, "ADMISSIONS.csv"),
        "chartevents":      os.path.join(base, "CHARTEVENTS.csv"),
        "cost":             os.path.join(base, "COST.csv"),
        "d_icd_diagnoses":  os.path.join(base, "D_ICD_DIAGNOSES.csv"),
        "d_icd_procedures": os.path.join(base, "D_ICD_PROCEDURES.csv"),
        "d_items":          os.path.join(base, "D_ITEMS.csv"),
        "d_labitems":       os.path.join(base, "D_LABITEMS.csv"),
        "diagnoses_icd":    os.path.join(base, "DIAGNOSES_ICD.csv"),
        "icustays":         os.path.join(base, "ICUSTAYS.csv"),
        "inputevents_cv":   os.path.join(base, "INPUTEVENTS_CV.csv"),
        "labevents":        os.path.join(base, "LABEVENTS.csv"),
        "microbiologyevents": os.path.join(base, "MICROBIOLOGYEVENTS.csv"),
        "outputevents":     os.path.join(base, "OUTPUTEVENTS.csv"),
        "patients":         os.path.join(base, "PATIENTS.csv"),
        "prescriptions":    os.path.join(base, "PRESCRIPTIONS.csv"),
        "procedures_icd":   os.path.join(base, "PROCEDURES_ICD.csv"),
        "transfers":        os.path.join(base, "TRANSFERS.csv"),
    }


def _eicu_ehr_dict():
    base = os.path.join(_DATASET_PATH, "eicu")
    return {
        "allergy":       os.path.join(base, "allergy.csv"),
        "cost":          os.path.join(base, "cost.csv"),
        "diagnosis":     os.path.join(base, "diagnosis.csv"),
        "intakeoutput":  os.path.join(base, "intakeoutput.csv"),
        "lab":           os.path.join(base, "lab.csv"),
        "medication":    os.path.join(base, "medication.csv"),
        "microlab":      os.path.join(base, "microlab.csv"),
        "patient":       os.path.join(base, "patient.csv"),
        "treatment":     os.path.join(base, "treatment.csv"),
        "vitalperiodic": os.path.join(base, "vitalperiodic.csv"),
    }


def db_loader(target_ehr):
    ehr_dict = _mimic_ehr_dict() if _DATASET == "mimic_iii" else _eicu_ehr_dict()
    data = pd.read_csv(ehr_dict[target_ehr])
    return data


def data_filter(data, argument):
    backup_data = data
    commands = argument.split("||")
    for i in range(len(commands)):
        column_name = ""
        value = ""
        try:
            if ">=" in commands[i]:
                command = commands[i].split(">=")
                column_name, value = command[0], command[1]
                try:
                    value = type(data[column_name][0])(value)
                except Exception:
                    pass
                data = data[data[column_name] >= value]
            elif "<=" in commands[i]:
                command = commands[i].split("<=")
                column_name, value = command[0], command[1]
                try:
                    value = type(data[column_name][0])(value)
                except Exception:
                    pass
                data = data[data[column_name] <= value]
            elif ">" in commands[i]:
                command = commands[i].split(">")
                column_name, value = command[0], command[1]
                try:
                    value = type(data[column_name][0])(value)
                except Exception:
                    pass
                data = data[data[column_name] > value]
            elif "<" in commands[i]:
                command = commands[i].split("<")
                column_name, value = command[0], command[1]
                if value[0] in ("'", '"'):
                    value = value[1:-1]
                try:
                    value = type(data[column_name][0])(value)
                except Exception:
                    pass
                data = data[data[column_name] < value]
            elif "=" in commands[i]:
                command = commands[i].split("=")
                column_name, value = command[0], command[1]
                if value[0] in ("'", '"'):
                    value = value[1:-1]
                try:
                    examplar = backup_data[column_name].tolist()[0]
                    value = type(examplar)(value)
                except Exception:
                    pass
                data = data[data[column_name] == value]
            elif " in " in commands[i]:
                command = commands[i].split(" in ")
                column_name = command[0]
                value = command[1]
                value_list = [s.strip() for s in value.strip("[]").split(",")]
                value_list = [s.strip("'").strip('"') for s in value_list]
                value_list = list(map(type(data[column_name][0]), value_list))
                data = data[data[column_name].isin(value_list)]
            elif "max" in commands[i]:
                column_name = commands[i].split("max(")[1].split(")")[0]
                data = data[data[column_name] == data[column_name].max()]
            elif "min" in commands[i]:
                column_name = commands[i].split("min(")[1].split(")")[0]
                data = data[data[column_name] == data[column_name].min()]
        except Exception:
            if column_name not in data.columns.tolist():
                columns = ", ".join(data.columns.tolist())
                raise Exception(
                    "The filtering query {} is incorrect. Please modify the column name "
                    "or use LoadDB to read another table. The column names in the current "
                    "DB are {}.".format(commands[i], columns)
                )
            if column_name == "" or value == "":
                raise Exception(
                    "The filtering query {} is incorrect. There is syntax error in the "
                    "command. Please modify the condition or use LoadDB to read another "
                    "table.".format(commands[i])
                )
        if len(data) == 0:
            column_values = list(set(backup_data[column_name].tolist()))
            if "=" in commands[i] and value not in column_values and ">=" not in commands[i] and "<=" not in commands[i]:
                levenshtein_dist = {}
                for cv in column_values:
                    levenshtein_dist[cv] = Levenshtein.distance(str(cv), str(value))
                levenshtein_dist = sorted(levenshtein_dist.items(), key=lambda x: x[1])
                column_values = [item[0] for item in levenshtein_dist[:5]]
                column_values = ", ".join([str(item) for item in column_values])
                raise Exception(
                    "The filtering query {} is incorrect. There is no {} value in the "
                    "column. Five example values in the column are {}. Please check if "
                    "you get the correct {} value.".format(commands[i], value, column_values, column_name)
                )
            else:
                return data
    return data


def get_value(data, argument):
    try:
        commands = argument.split(", ")
        if len(commands) == 1:
            column = argument
            while column[0] in ("[", "'"):
                column = column[1:]
            while column[-1] in ("]", "'"):
                column = column[:-1]
            if len(data) == 1:
                return str(data.iloc[0][column])
            else:
                answer_list = list(set(data[column].tolist()))
                return ", ".join([str(i) for i in answer_list])
        else:
            column = commands[0]
            op = commands[-1]
            res_list = data[column].tolist()
            if "mean" in op:
                return sum(float(i) for i in res_list) / len(res_list)
            elif "max" in op:
                try:
                    return max(float(i) for i in res_list)
                except Exception:
                    return max(str(i) for i in res_list)
            elif "min" in op:
                try:
                    return min(float(i) for i in res_list)
                except Exception:
                    return min(str(i) for i in res_list)
            elif "sum" in op:
                return sum(float(i) for i in res_list)
            elif "list" in op:
                return [str(i) for i in res_list]
            else:
                raise Exception("The operation {} contains syntax errors.".format(op))
    except Exception:
        column_values = ", ".join(data.columns.tolist())
        raise Exception(
            "The column name {} is incorrect. Please check the column name and make "
            "necessary changes. The columns in this table include {}.".format(argument, column_values)
        )


def sql_interpreter(command):
    if _DATASET == "mimic_iii":
        db_path = os.path.join(_DATASET_PATH, "mimic_iii", "mimic_iii.db")
    else:
        db_path = os.path.join(_DATASET_PATH, "eicu", "eicu.db")
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    results = cur.execute(command).fetchall()
    con.close()
    return results


def date_calculator(argument):
    try:
        if _DATASET == "mimic_iii":
            db_path = os.path.join(_DATASET_PATH, "mimic_iii", "mimic_iii.db")
        else:
            db_path = os.path.join(_DATASET_PATH, "eicu", "eicu.db")
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        results = cur.execute(
            "select datetime(current_time, '{}')".format(argument)
        ).fetchall()[0][0]
        con.close()
    except Exception:
        raise Exception(
            "The date calculator {} is incorrect. Please check the syntax and make "
            "necessary changes. For the current date and time, please call "
            "Calendar('0 year').".format(argument)
        )
    return results
