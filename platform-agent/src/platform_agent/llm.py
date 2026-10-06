import json

import ollama
from pydantic import ValidationError

from platform_agent.contracts import LLMDiagnosis, ToolResult

DEFAULT_MODEL = "qwen2.5:3b"


class LLMError(RuntimeError):
    """Raised when local LLM reasoning cannot produce a valid diagnosis."""


def build_diagnosis_prompt(
    trace: list[ToolResult],
) -> str:
    """Build a bounded prompt from previously collected tool evidence."""

    evidence = [
        result.model_dump(mode="json")
        for result in trace
    ]

    return (
        "You are a read-only Site Reliability Engineering diagnostic assistant.\n\n"
        "Analyze only the operational evidence provided below.\n"
        "Do not invent evidence.\n"
        "Do not claim that you executed commands or changed infrastructure.\n"
        "Do not recommend destructive actions when a safer diagnostic action exists.\n"
        "If the evidence is insufficient, explicitly say so and lower confidence.\n\n"
        "Return a concise structured diagnosis containing exactly:\n"
        "- summary\n"
        "- probable_cause\n"
        "- confidence: low, medium, or high\n"
        "- recommended_action\n\n"
        "Operational evidence:\n"
        f"{json.dumps(evidence, indent=2, sort_keys=True)}"
    )


def diagnose_tool_trace(
    trace: list[ToolResult],
    model: str = DEFAULT_MODEL,
) -> LLMDiagnosis:
    """Use Ollama to reason over already-collected operational evidence."""

    if not trace:
        raise ValueError("trace must contain at least one tool result.")

    prompt = build_diagnosis_prompt(trace)

    try:
        response = ollama.chat(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            format=LLMDiagnosis.model_json_schema(),
            options={
                "temperature": 0,
            },
        )
    except Exception as error:
        raise LLMError(
            f"Ollama request failed: {error}"
        ) from error

    content = response.message.content

    if not isinstance(content, str) or not content.strip():
        raise LLMError("Ollama returned an empty diagnosis.")

    try:
        return LLMDiagnosis.model_validate_json(content)
    except ValidationError as error:
        raise LLMError(
            "Ollama returned a diagnosis that failed schema validation."
        ) from error
