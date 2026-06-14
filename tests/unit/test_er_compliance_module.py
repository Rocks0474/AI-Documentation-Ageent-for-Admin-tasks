"""Exhaustive tests for the deterministic ER compliance module (Module B).

It is deterministic and must never produce incorrect results — every rule has
a test, plus the CLEAR path.
"""

from __future__ import annotations

from agents.er.compliance_module import ERComplianceModule

module = ERComplianceModule()


def test_termination_triggers_hard_stop():
    result = module.check(
        facts="manager wants to proceed with termination of employee",
        jurisdiction="JP",
    )
    assert result.result == "HARD_STOP"
    assert "TERMINATION" in result.triggered_rules
    assert result.hitl_tier == "MANDATORY"
    assert result.legal_agent_required is True


def test_harassment_allegation_triggers_hard_stop():
    result = module.check(
        facts="employee has raised a harassment complaint against manager",
        jurisdiction="US-CA",
    )
    assert result.result == "HARD_STOP"
    assert "HARASSMENT_ALLEGATION" in result.triggered_rules
    assert result.legal_agent_required is True


def test_discrimination_triggers_harassment_rule():
    result = module.check(
        facts="alleged discrimination based on protected class",
        jurisdiction="EU",
    )
    assert "HARASSMENT_ALLEGATION" in result.triggered_rules


def test_warn_trigger_us_fed():
    result = module.check(facts="planned reduction", jurisdiction="US-FED", employee_count=120)
    assert "WARN_TRIGGER_US" in result.triggered_rules


def test_warn_not_triggered_below_threshold():
    result = module.check(facts="planned reduction", jurisdiction="US-FED", employee_count=80)
    assert "WARN_TRIGGER_US" not in result.triggered_rules


def test_calwarn_trigger_us_ca():
    result = module.check(facts="planned reduction", jurisdiction="US-CA", employee_count=60)
    assert "CALWARN_TRIGGER" in result.triggered_rules


def test_seiri_kaiko_jp():
    result = module.check(facts="company is planning a mass layoff", jurisdiction="JP")
    assert result.result == "HARD_STOP"
    assert "SEIRI_KAIKO_JP" in result.triggered_rules
    assert result.legal_agent_required is True


def test_eu_collective_dismissal():
    result = module.check(facts="collective redundancy programme", jurisdiction="EU")
    assert "EU_COLLECTIVE_DISMISSAL" in result.triggered_rules
    assert result.legal_agent_required is True


def test_union_demand_japanese():
    result = module.check(facts="組合からの団体交渉の要求", jurisdiction="JP")
    assert "UNION_DEMAND" in result.triggered_rules
    assert result.legal_agent_required is True


def test_union_demand_english():
    result = module.check(facts="received a union demand letter", jurisdiction="US-FED")
    assert "UNION_DEMAND" in result.triggered_rules


def test_works_council_present():
    result = module.check(
        facts="routine consultation", jurisdiction="EU", works_council_present=True
    )
    assert "WORKS_COUNCIL" in result.triggered_rules


def test_protected_leave_japanese():
    result = module.check(facts="育児休業中の懲戒検討", jurisdiction="JP")
    assert "PROTECTED_LEAVE" in result.triggered_rules


def test_protected_leave_fmla():
    result = module.check(facts="employee is on FMLA leave", jurisdiction="US-FED")
    assert "PROTECTED_LEAVE" in result.triggered_rules


def test_whistleblower_signal_jp():
    result = module.check(
        facts="employee has filed a 公益通報 regarding accounting irregularities",
        jurisdiction="JP",
    )
    assert result.result == "HARD_STOP"
    assert "WHISTLEBLOWER" in result.triggered_rules


def test_whistleblower_signal_english():
    result = module.check(facts="a whistleblower report was filed", jurisdiction="US-FED")
    assert "WHISTLEBLOWER" in result.triggered_rules


def test_data_breach_pii():
    result = module.check(
        facts="a data breach exposed employee records", jurisdiction="JP"
    )
    assert "DATA_BREACH_PII" in result.triggered_rules


def test_routine_policy_query_clears():
    result = module.check(
        facts="employee asking about remote work policy", jurisdiction="JP"
    )
    assert result.result == "CLEAR"
    assert result.triggered_rules == []
    assert result.legal_agent_required is False
    assert result.hitl_tier == "NONE"


def test_multiple_rules_collected():
    result = module.check(
        facts="termination tied to a harassment complaint", jurisdiction="JP"
    )
    assert {"TERMINATION", "HARASSMENT_ALLEGATION"} <= set(result.triggered_rules)
