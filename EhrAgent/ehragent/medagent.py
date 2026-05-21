import time
import json
from openai import OpenAI
from autogen.agentchat import UserProxyAgent
from termcolor import colored
import Levenshtein
from toolset_high import run_code
from compiler_agent import CompilerSuccessButExecFailed


class MedAgent(UserProxyAgent):
    def __init__(
        self,
        name,
        api_key,
        model,
        is_termination_msg=None,
        max_consecutive_auto_reply=None,
        human_input_mode="ALWAYS",
        function_map=None,
        code_execution_config=None,
        default_auto_reply="",
        llm_config=False,
        system_message="",
    ):
        super().__init__(
            name=name,
            system_message=system_message,
            is_termination_msg=is_termination_msg,
            max_consecutive_auto_reply=max_consecutive_auto_reply,
            human_input_mode=human_input_mode,
            function_map=function_map,
            code_execution_config=code_execution_config,
            llm_config=llm_config,
            default_auto_reply=default_auto_reply,
        )
        self._openai_client = OpenAI(api_key=api_key)
        self._model = model
        self.question = ""
        self.code = ""
        self.knowledge = ""
        self.mode = "baseline"
        self.compiler_agent = None
        self.compiler_debugger_agent = None

    def set_mode(self, mode, compiler_agent=None, compiler_debugger_agent=None):
        self.mode = mode
        self.compiler_agent = compiler_agent
        self.compiler_debugger_agent = compiler_debugger_agent

    def retrieve_knowledge(self, query):
        if self.dataset == "mimic_iii":
            from prompts_mimic import RetrKnowledge
        else:
            from prompts_eicu import RetrKnowledge
        query_message = RetrKnowledge.format(question=query)
        messages = [
            {"role": "system", "content": "You are an AI assistant that helps people find information."},
            {"role": "user", "content": query_message},
        ]
        patience = 2
        while patience > 0:
            patience -= 1
            try:
                response = self._openai_client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    temperature=0,
                    max_tokens=800,
                )
                prediction = response.choices[0].message.content.strip()
                if prediction:
                    return prediction
            except Exception as e:
                print(e)
                time.sleep(30)
        return "Fail to retrieve related knowledge, please try again later."

    def retrieve_examples(self, query):
        levenshtein_dist = {}
        for i in range(len(self.memory)):
            question = self.memory[i]["question"]
            levenshtein_dist[i] = Levenshtein.distance(query, question)
        levenshtein_dist = sorted(levenshtein_dist.items(), key=lambda x: x[1])
        selected_indexes = [levenshtein_dist[i][0] for i in range(min(self.num_shots, len(levenshtein_dist)))]
        examples = []
        for i in selected_indexes:
            template = "Question: {}\nKnowledge:\n{}\nSolution:\n{}\n".format(
                self.memory[i]["question"], self.memory[i]["knowledge"], self.memory[i]["code"]
            )
            examples.append(template)
        return "\n".join(examples)

    def generate_init_message(self, **context):
        if self.dataset == "mimic_iii":
            from prompts_mimic import EHRAgent_Message_Prompt
        else:
            from prompts_eicu import EHRAgent_Message_Prompt
        self.question = context["message"]
        knowledge = self.retrieve_knowledge(context["message"])
        self.knowledge = knowledge
        examples = self.retrieve_examples(context["message"])
        return EHRAgent_Message_Prompt.format(
            examples=examples, knowledge=knowledge, question=context["message"]
        )

    def send(self, message, recipient, request_reply=None, silent=False):
        valid = self._append_oai_message(message, "assistant", recipient)
        if valid:
            recipient.receive(message, self, request_reply, silent)
        else:
            raise ValueError("Message can't be converted into a valid ChatCompletion message.")

    def initiate_chat(self, recipient, clear_history=True, silent=False, **context):
        self._prepare_chat(recipient, clear_history)
        self.send(self.generate_init_message(**context), recipient, silent=silent)

    def receive(self, message, sender, request_reply=None, silent=False):
        self._process_received_message(message, sender, silent)
        if request_reply is False or (request_reply is None and self.reply_at_receive[sender] is False):
            return
        reply = self.generate_reply(messages=self.chat_messages[sender], sender=sender)
        if reply is not None:
            self.send(reply, sender, silent=silent)

    def error_debugger(self, code, error_info):
        if self.dataset == "mimic_iii":
            from prompts_mimic import CodeDebugger
        else:
            from prompts_eicu import CodeDebugger
        query_message = CodeDebugger.format(
            question=self.question, code=code, error_info=error_info
        )
        messages = [
            {"role": "system", "content": "You are an AI assistant that helps people debug their code. Only list one most possible reason to the errors."},
            {"role": "user", "content": query_message},
        ]
        patience = 2
        while patience > 0:
            patience -= 1
            try:
                response = self._openai_client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    temperature=0,
                    max_tokens=800,
                )
                prediction = response.choices[0].message.content.strip()
                if prediction:
                    return prediction
            except Exception as e:
                print(e)
                time.sleep(30)
        return "Fail to diagnose the reasons to the errors."

    def execute_function(self, func_call):
        func_name = func_call.get("name", "")
        func = self._function_map.get(func_name, None)
        is_exec_success = False

        if func is not None:
            input_string = self._format_json_str(func_call.get("arguments", "{}"))
            try:
                arguments = json.loads(input_string)
            except json.JSONDecodeError as e:
                arguments_string = func_call["arguments"].split(': "')[-1].split('", ')[0]
                arguments = {"cell": arguments_string}

            if arguments is not None:
                print(colored(f"\n>>>>>>>> EXECUTING FUNCTION {func_name}...", "magenta"), flush=True)
                self.code = arguments["cell"]

                if self.mode == "compiler_agent":
                    try:
                        compiler_response = self.compiler_agent.evaluate(self.question, self.code)
                        if compiler_response.startswith("[ERROR]"):
                            error_msg = compiler_response[len("[ERROR]"):].strip()
                            reasons = self.error_debugger(self.code, error_msg)
                            content = error_msg + "\nPotential Reasons: " + reasons
                        else:
                            content = run_code(self.code)
                            if "error" in content.lower():
                                raise CompilerSuccessButExecFailed(content)
                            is_exec_success = True
                    except CompilerSuccessButExecFailed:
                        raise
                    except Exception as e:
                        content = f"Error: {e}"

                elif self.mode == "newdebugger":
                    try:
                        compiler_response = self.compiler_debugger_agent.evaluate(self.question, self.code)
                        if compiler_response.startswith("[ERROR]"):
                            content = compiler_response[len("[ERROR]"):].strip()
                        else:
                            content = run_code(self.code)
                            if "error" in content.lower():
                                raise CompilerSuccessButExecFailed(content)
                            is_exec_success = True
                    except CompilerSuccessButExecFailed:
                        raise
                    except Exception as e:
                        content = f"Error: {e}"

                else:  # baseline
                    try:
                        content = func(**arguments)
                        is_exec_success = True
                    except Exception as e:
                        content = f"Error: {e}"
                    if "error" in content or "Error" in content:
                        reasons = self.error_debugger(self.code, content)
                        content = content + "\nPotential Reasons: " + reasons
        else:
            content = f"Error: Function {func_name} not found."

        return is_exec_success, {
            "name": func_name,
            "role": "function",
            "content": str(content),
        }

    def update_memory(self, num_shots, memory):
        self.num_shots = num_shots
        self.memory = memory

    def register_dataset(self, dataset):
        self.dataset = dataset
