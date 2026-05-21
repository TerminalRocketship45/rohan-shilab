from openai import OpenAI


class CompilerSuccessButExecFailed(Exception):
    """Raised when Compiler Agent says [SUCCESS] but real run_code() fails.
    Caught by pipeline to mark question as INCOMPLETED without feeding error back to AI."""
    pass


_PROMPT_TEMPLATE = """Here are examples of how to evaluate EHR query code:

{few_shot_examples}

Now evaluate the following code written to answer this question:
Question: {question}

Code:
{code}

Respond with [SUCCESS] or [ERROR] followed by the result or error message."""


class CompilerAgent:
    """LLM that checks code against EHR schema before real execution.
    Returns [SUCCESS]\\n<result> or [ERROR]\\n<error message>."""

    def __init__(self, api_key, model, dataset, few_shot_examples, system_message):
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.dataset = dataset
        self.few_shot_examples = few_shot_examples
        self.system_message = system_message

    def evaluate(self, question, code):
        prompt = _PROMPT_TEMPLATE.format(
            few_shot_examples=self.few_shot_examples,
            question=question,
            code=code,
        )
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.system_message},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            max_tokens=500,
        )
        return response.choices[0].message.content.strip()


class CompilerDebuggerAgent:
    """Combined LLM that checks code AND provides a suggested fix in one call.
    Returns [SUCCESS]\\n<result> or [ERROR]\\n<error>\\nSuggested fix: <fix>."""

    def __init__(self, api_key, model, dataset, few_shot_examples, system_message):
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.dataset = dataset
        self.few_shot_examples = few_shot_examples
        self.system_message = system_message

    def evaluate(self, question, code):
        prompt = _PROMPT_TEMPLATE.format(
            few_shot_examples=self.few_shot_examples,
            question=question,
            code=code,
        )
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.system_message},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            max_tokens=600,
        )
        return response.choices[0].message.content.strip()
