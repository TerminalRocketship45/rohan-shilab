import sys
import time
import os
import traceback
from termcolor import colored

_CODE_HEADER = """from tools import tabtools, calculator
Calculate = calculator.WolframAlphaCalculator
LoadDB = tabtools.db_loader
FilterDB = tabtools.data_filter
GetValue = tabtools.get_value
SQLInterpreter = tabtools.sql_interpreter
Calendar = tabtools.date_calculator
"""


def run_code(cell):
    try:
        global_var = {"answer": 0}
        exec(_CODE_HEADER + cell, global_var)
        cell = "\n".join(
            [line for line in cell.split("\n") if line.strip() and not line.strip().startswith("#")]
        )
        if "answer" not in cell.split("\n")[-1]:
            return "Please save the answer to the question in the variable 'answer'."
        return str(global_var["answer"])
    except Exception as e:
        error_info = traceback.format_exc()
        code = _CODE_HEADER + cell
        if "SyntaxError" in str(repr(e)):
            error_line = str(repr(e))
            error_type = error_line.split("(")[0]
            error_message = error_line.split(",")[0].split("(")[1]
            error_line = error_line.split('"')[1]
        elif "KeyError" in str(repr(e)):
            code_lines = code.split("\n")
            key = str(repr(e)).split("'")[1]
            error_type = str(repr(e)).split("(")[0]
            error_line = ""
            for line in code_lines:
                if key in line:
                    error_line = line
            error_message = str(repr(e))
        elif "TypeError" in str(repr(e)):
            error_type = str(repr(e)).split("(")[0]
            error_message = str(e)
            function_mapping_dict = {
                "get_value": "GetValue",
                "data_filter": "FilterDB",
                "db_loader": "LoadDB",
                "sql_interpreter": "SQLInterpreter",
                "date_calculator": "Calendar",
            }
            error_key = ""
            for key in function_mapping_dict:
                if key in error_message:
                    error_message = error_message.replace(key, function_mapping_dict[key])
                    error_key = function_mapping_dict[key]
            code_lines = code.split("\n")
            error_line = ""
            for line in code_lines:
                if error_key in line:
                    error_line = line
        else:
            error_type = ""
            error_message = str(repr(e)).split("('")[-1].split("')")[0]
            error_line = ""

        if error_type and error_line:
            error_info = '{}: {}. The error messages occur in the code line "{}".'.format(
                error_type, error_message, error_line
            )
        else:
            error_info = "Error: {}.".format(error_message)
        error_info += "\nPlease make modifications accordingly and make sure the rest code works well with the modification."
        return error_info
