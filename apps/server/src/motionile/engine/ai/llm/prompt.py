import base64
import json
import re
from collections.abc import Sequence
from typing import Final

from pydantic import BaseModel, ValidationError

from motionile.engine.ai.llm.models import ImageBlock, LlmCall, UserBlock

type Message = dict[str, object]

EPHEMERAL: Final = {"type": "ephemeral"}
MAX_REPORTED_ERRORS: Final = 20
FENCE_PATTERN: Final = re.compile(r"^```[A-Za-z0-9_-]*\s*\n(.*?)\n?```\s*$", re.DOTALL)


def cache_breakpoint_indexes(count: int) -> frozenset[int]:
    if count <= 0:
        return frozenset()
    return frozenset({0, count - 1})


def system_message(blocks: Sequence[str], *, cache_control: bool) -> Message:
    if not cache_control:
        return {"role": "system", "content": "\n\n".join(blocks)}
    breakpoints = cache_breakpoint_indexes(len(blocks))
    parts: list[dict[str, object]] = []
    for index, block in enumerate(blocks):
        part: dict[str, object] = {"type": "text", "text": block}
        if index in breakpoints:
            part["cache_control"] = dict(EPHEMERAL)
        parts.append(part)
    return {"role": "system", "content": parts}


def user_parts(blocks: Sequence[UserBlock]) -> list[dict[str, object]]:
    parts: list[dict[str, object]] = []
    for block in blocks:
        if isinstance(block, ImageBlock):
            encoded = base64.b64encode(block.png).decode("ascii")
            parts.append({"type": "text", "text": block.label})
            parts.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}})
        else:
            parts.append({"type": "text", "text": block})
    return parts


def json_schema_of(output: type[BaseModel]) -> dict[str, object]:
    return output.model_json_schema(by_alias=True)


def schema_instruction(output: type[BaseModel]) -> str:
    schema = json.dumps(json_schema_of(output), separators=(",", ":"), sort_keys=True)
    return (
        "Reply with a single JSON object that conforms to this JSON schema. "
        "Write no markdown fences and no text before or after the object.\n"
        f"<json_schema>{schema}</json_schema>"
    )


def response_format_for(output: type[BaseModel]) -> dict[str, object]:
    return {
        "type": "json_schema",
        "json_schema": {"name": output.__name__, "schema": json_schema_of(output), "strict": False},
    }


def build_messages(call: LlmCall, *, cache_control: bool, instruction: str | None) -> list[Message]:
    messages: list[Message] = []
    if call.system_blocks:
        messages.append(system_message(call.system_blocks, cache_control=cache_control))
    parts = user_parts(call.user_blocks)
    if instruction is not None:
        parts.append({"type": "text", "text": instruction})
    messages.append({"role": "user", "content": parts})
    return messages


def reask_messages(messages: Sequence[Message], previous_output: str, problems: str) -> list[Message]:
    return [
        *messages,
        {"role": "assistant", "content": previous_output},
        {
            "role": "user",
            "content": (
                "Your previous reply did not match the required JSON schema. "
                "Reply again with the complete corrected JSON object only.\n"
                f"<validation_errors>\n{problems}\n</validation_errors>"
            ),
        },
    ]


def describe_validation_errors(error: ValidationError) -> str:
    lines: list[str] = []
    for item in error.errors(include_url=False, include_context=False, include_input=False)[:MAX_REPORTED_ERRORS]:
        location = ".".join(str(part) for part in item["loc"]) or "(root)"
        lines.append(f"- {location}: {item['msg']}")
    return "\n".join(lines)


def json_candidate(text: str) -> str:
    stripped = text.strip()
    fenced = FENCE_PATTERN.match(stripped)
    if fenced is not None:
        return fenced.group(1).strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end > start:
        return stripped[start : end + 1]
    return stripped


def summarize_user_blocks(blocks: Sequence[UserBlock]) -> str:
    return "\n".join(f"[image: {block.label}]" if isinstance(block, ImageBlock) else block for block in blocks)
