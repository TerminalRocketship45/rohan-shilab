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

import autogen
from medagent import MedAgent
from compiler_agent import CompilerAgent
from toolset_high import run_code
import tools.tabtools as tabtools


class SchemaAwareMedAgent(MedAgent):
    """MedAgent subclass that injects a parameterized schema into the initial message."""

    def set_schema(self, schema_str, prompt_builder):
        self.schema_str = schema_str
        self.prompt_builder = prompt_builder

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


def build_agents(pipeline_type, schema_str, model, api_key, seed, dataset, dataset_path):
    """Build (user_proxy, chatbot) for a given pipeline type and schema string.

    pipeline_type: "compiler_agent" | "baseline"
    schema_str:    "" | dataset schema string | ReFoRCE-generated schema string
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

    cfg = {"model": model, "api_key": api_key, "api_type": "openai"}
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

    if pipeline_type == "compiler_agent":
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
