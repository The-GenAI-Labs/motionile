import re
from pathlib import Path

import pytest

from motionile.engine.ai.guardrails import POLICY_MESSAGES, PolicyCode, is_refusal_code, policy_message
from motionile.engine.ai.guardrails.decision import GuardDecision, GuardResult
from motionile.engine.ai.guardrails.policy import INPUT_REFUSAL_CODES

POLICY_DOC = Path(__file__).resolve().parents[7] / "docs" / "ai-policy.md"
ROW = re.compile(r"^\|\s*`(?P<code>policy_[a-z_]+)`\s*\|(?P<refused>.*)\|\s*(?P<message>[^|]+?)\s*\|\s*$")


def documented_rows() -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in POLICY_DOC.read_text(encoding="utf-8").splitlines():
        match = ROW.match(line)
        if match is not None:
            rows[match["code"]] = match["message"]
    return rows


def test_codes_are_exactly_the_documented_codes() -> None:
    assert {code.value for code in PolicyCode} == set(documented_rows())


def test_messages_match_the_documented_table() -> None:
    documented = documented_rows()

    assert {code.value: message for code, message in POLICY_MESSAGES.items()} == documented


def test_every_code_has_a_message_and_a_lowercase_snake_case_value() -> None:
    for code in PolicyCode:
        assert policy_message(code)
        assert re.fullmatch(r"policy_[a-z_]+", code.value)


def test_is_refusal_code() -> None:
    assert is_refusal_code("policy_weapons")
    assert is_refusal_code("policy_output_blocked")
    assert not is_refusal_code("llm_unavailable")
    assert not is_refusal_code("")


def test_the_output_code_is_not_an_input_refusal() -> None:
    assert PolicyCode.OUTPUT_BLOCKED not in INPUT_REFUSAL_CODES
    assert INPUT_REFUSAL_CODES | {PolicyCode.OUTPUT_BLOCKED} == set(PolicyCode)


def test_refusal_results_carry_the_documented_message() -> None:
    result = GuardResult.refuse(PolicyCode.SELF_HARM)

    assert not result.allowed
    assert result.code is PolicyCode.SELF_HARM
    assert result.message == documented_rows()["policy_self_harm"]


def test_allowed_results_carry_nothing() -> None:
    result = GuardResult.allow()

    assert result.allowed
    assert result.code is None
    assert result.message is None


def test_decision_validation() -> None:
    assert GuardDecision(verdict="allow").code is None
    assert GuardDecision(verdict="refuse", code=PolicyCode.ABUSE).code is PolicyCode.ABUSE
    with pytest.raises(ValueError, match="no code"):
        GuardDecision(verdict="allow", code=PolicyCode.ABUSE)
    with pytest.raises(ValueError, match="policy code"):
        GuardDecision(verdict="refuse")


def test_decision_wire_form_is_camel_case_and_strict() -> None:
    decision = GuardDecision.model_validate(
        {
            "verdict": "refuse",
            "code": "policy_malware",
            "reason": "  asks for a keylogger ",
            "detected": ["policy_malware"],
        }
    )

    assert decision.reason == "asks for a keylogger"
    assert decision.detected == [PolicyCode.MALWARE]
    with pytest.raises(ValueError, match="extra"):
        GuardDecision.model_validate({"verdict": "allow", "unexpected": 1})
    with pytest.raises(ValueError, match="policy"):
        GuardDecision.model_validate({"verdict": "refuse", "code": "policy_invented"})
