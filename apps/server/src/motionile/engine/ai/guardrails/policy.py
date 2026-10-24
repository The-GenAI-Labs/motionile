from enum import StrEnum
from typing import Final


class PolicyCode(StrEnum):
    WEAPONS = "policy_weapons"
    MALWARE = "policy_malware"
    SELF_HARM = "policy_self_harm"
    ABUSE = "policy_abuse"
    SEXUAL_CONTENT = "policy_sexual_content"
    HARASSMENT = "policy_harassment"
    POLITICAL_PERSUASION = "policy_political_persuasion"
    PERSONAL_DATA = "policy_personal_data"
    PROMPT_INJECTION = "policy_prompt_injection"
    PROMPT_EXTRACTION = "policy_prompt_extraction"
    UNSUPPORTED_REQUEST = "policy_unsupported_request"
    OUTPUT_BLOCKED = "policy_output_blocked"


POLICY_MESSAGES: Final[dict[PolicyCode, str]] = {
    PolicyCode.WEAPONS: (
        "Motionile cannot make videos that explain how to build or use weapons. "
        "Try a topic about the history or science behind it."
    ),
    PolicyCode.MALWARE: (
        "Motionile cannot make videos that teach how to build malware or attack systems. "
        "Try explaining how the attack class is defended against."
    ),
    PolicyCode.SELF_HARM: (
        "Motionile cannot make this video. If you or someone you know is struggling, "
        "please reach out to a local helpline or someone you trust."
    ),
    PolicyCode.ABUSE: "Motionile cannot make videos that involve abuse or exploitation.",
    PolicyCode.SEXUAL_CONTENT: "Motionile does not make sexually explicit videos.",
    PolicyCode.HARASSMENT: "Motionile cannot make videos that target a real person or group.",
    PolicyCode.POLITICAL_PERSUASION: (
        "Motionile does not make persuasive political videos. A neutral explainer of how the system works is fine."
    ),
    PolicyCode.PERSONAL_DATA: "Your request contains personal information. Remove it and try again.",
    PolicyCode.PROMPT_INJECTION: (
        "Motionile could not use this request. Describe the topic you want explained and try again."
    ),
    PolicyCode.PROMPT_EXTRACTION: (
        "Motionile could not use this request. Describe the topic you want explained and try again."
    ),
    PolicyCode.UNSUPPORTED_REQUEST: "Motionile makes explainer videos. Tell it what you want explained.",
    PolicyCode.OUTPUT_BLOCKED: (
        "The video could not be completed safely. Your credits were returned. Try rephrasing your request."
    ),
}

INPUT_REFUSAL_CODES: Final[frozenset[PolicyCode]] = frozenset(PolicyCode) - {PolicyCode.OUTPUT_BLOCKED}


def is_refusal_code(value: str) -> bool:
    return value in PolicyCode


def policy_message(code: PolicyCode) -> str:
    return POLICY_MESSAGES[code]
