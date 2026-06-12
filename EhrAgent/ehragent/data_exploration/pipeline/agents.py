# EhrAgent/ehragent/data_exploration/pipeline/agents.py
import os
import sys

# Add parent directories so legacy EhrAgent modules are importable
_HERE = os.path.dirname(os.path.abspath(__file__))
_EHRAGENT_INNER = os.path.abspath(os.path.join(_HERE, "..", ".."))   # EhrAgent/ehragent/
_EHRAGENT_OUTER = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))  # EhrAgent/
for _p in [_EHRAGENT_OUTER, _EHRAGENT_INNER]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import anthropic
import autogen
from medagent import MedAgent
from compiler_agent import CompilerAgent
from toolset_high import run_code
import tools.tabtools as tabtools


class _AnthropicCompilerAgent:
    """Drop-in replacement for CompilerAgent using the Anthropic SDK."""

    def __init__(self, api_key, model, dataset, few_shot_examples, system_message):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.system_message = system_message
        self.few_shot_examples = few_shot_examples

    def evaluate(self, question, code):
        prompt = (
            f"{self.few_shot_examples}\n\n"
            f"Now evaluate this:\nQuestion: {question}\nCode:\n{code}"
        )
        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=512,
                system=self.system_message,
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text.strip()
            if "[SUCCESS]" in text or "[ERROR]" in text:
                return text
            return f"[ERROR] Unexpected compiler response: {text[:200]}"
        except Exception as e:
            return f"[ERROR] Compiler call failed: {e}"


class SchemaAwareMedAgent(MedAgent):
    """MedAgent subclass that injects a parameterized schema and supports Anthropic."""

    def set_schema(self, schema_str, prompt_builder):
        self.schema_str = schema_str
        self.prompt_builder = prompt_builder

    def set_anthropic_client(self, client, model):
        self._anthropic_client = client
        self._anthropic_model = model

    def generate_init_message(self, message, **kwargs):
        self.question = message
        knowledge = self.retrieve_knowledge(message)
        self.knowledge = knowledge
        examples = self.retrieve_examples(message)
        return self.prompt_builder(
            schema_str=self.schema_str,
            examples=examples,
            knowledge=knowledge,
            question=message,
        )

    def retrieve_knowledge(self, query):
        if not hasattr(self, "_anthropic_client"):
            return super().retrieve_knowledge(query)
        if self.dataset == "mimic_iii":
            from prompts_mimic import RetrKnowledge
        else:
            from prompts_eicu import RetrKnowledge
        prompt = RetrKnowledge.format(question=query)
        for _ in range(2):
            try:
                resp = self._anthropic_client.messages.create(
                    model=self._anthropic_model,
                    max_tokens=800,
                    system="You are an AI assistant that helps people find information.",
                    messages=[{"role": "user", "content": prompt}],
                )
                text = resp.content[0].text.strip()
                if text:
                    return text
            except Exception:
                pass
        return "Fail to retrieve related knowledge, please try again later."

    def error_debugger(self, code, error_info):
        if not hasattr(self, "_anthropic_client"):
            return super().error_debugger(code, error_info)
        if self.dataset == "mimic_iii":
            from prompts_mimic import CodeDebugger
        else:
            from prompts_eicu import CodeDebugger
        prompt = CodeDebugger.format(question=self.question, code=code, error_info=error_info)
        for _ in range(2):
            try:
                resp = self._anthropic_client.messages.create(
                    model=self._anthropic_model,
                    max_tokens=800,
                    system="You are an AI assistant that helps people debug their code. Only list one most possible reason to the errors.",
                    messages=[{"role": "user", "content": prompt}],
                )
                text = resp.content[0].text.strip()
                if text:
                    return text
            except Exception:
                pass
        return "Fail to diagnose the reasons to the errors."


def build_agents(pipeline_type, schema_str, model, api_key, seed, dataset, dataset_path, provider="openai"):
    """Build (user_proxy, chatbot) for a given pipeline type and schema string.

    pipeline_type: "compiler_agent" | "baseline"
    schema_str:    "" | dataset schema string | ReFoRCE-generated schema string
    provider:      "openai" | "anthropic"
    """
    tabtools.configure(dataset_path, dataset)

    if dataset == "mimic_iii":
        from prompts.mimic_iii import (
            get_coding_agent_prompt,
            get_compiler_system_message,
            CompilerAgent_FewShot_Examples,
        )
    else:
        from prompts.eicu import (
            get_coding_agent_prompt,
            get_compiler_system_message,
            CompilerAgent_FewShot_Examples,
        )

    api_type = "anthropic" if provider == "anthropic" else "openai"
    cfg = {"model": model, "api_key": api_key, "api_type": api_type}
    llm_cfg = {
        "functions": [
            {
                "name": "python",
                "description": "run the entire code and return the execution result. Only generate the code.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "cell": {
                            "type": "string",
                            "description": "Valid Python code to execute.",
                        }
                    },
                    "required": ["cell"],
                },
            }
        ],
        "config_list": [cfg],
        "timeout": 120,
        "cache_seed": seed,
        "temperature": 0,
    }

    chatbot = autogen.agentchat.AssistantAgent(
        name="chatbot",
        system_message=(
            "For coding tasks, only use the functions you have been provided with. "
            "Reply TERMINATE when the task is done. Save the answers to the questions "
            "in the variable 'answer'. Please only generate the code."
        ),
        llm_config=llm_cfg,
    )

    user_proxy = SchemaAwareMedAgent(
        name="user_proxy",
        api_key=api_key,
        model=model,
        is_termination_msg=lambda x: x.get("content", "")
        and x.get("content", "").rstrip().endswith("TERMINATE"),
        human_input_mode="NEVER",
        max_consecutive_auto_reply=10,
        code_execution_config={"work_dir": "coding", "use_docker": False},
    )
    user_proxy.register_function(function_map={"python": run_code})
    user_proxy.register_dataset(dataset)
    user_proxy.set_schema(schema_str=schema_str, prompt_builder=get_coding_agent_prompt)

    if provider == "anthropic":
        anthr_client = anthropic.Anthropic(api_key=api_key)
        user_proxy.set_anthropic_client(anthr_client, model)

    if pipeline_type == "compiler_agent":
        if provider == "anthropic":
            ca = _AnthropicCompilerAgent(
                api_key=api_key,
                model=model,
                dataset=dataset,
                few_shot_examples=CompilerAgent_FewShot_Examples,
                system_message=get_compiler_system_message(schema_str),
            )
        else:
            ca = CompilerAgent(
                api_key=api_key,
                model=model,
                dataset=dataset,
                few_shot_examples=CompilerAgent_FewShot_Examples,
                system_message=get_compiler_system_message(schema_str),
            )
        user_proxy.set_mode("compiler_agent", compiler_agent=ca)
    # baseline: user_proxy.mode stays "baseline" (default in MedAgent)

    return user_proxy, chatbot
