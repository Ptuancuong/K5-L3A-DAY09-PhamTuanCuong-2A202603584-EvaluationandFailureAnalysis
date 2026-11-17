"""Regression test from docs/trace_case.md: seeded_regression C-002@11 (FM-03 ticket_trust).

The first wrong step is event 3, `model_override {"delay_days": 5}`: the agent replaces the order's
delay_days (2, from the DB) with the 5 days written in the ticket, which turns a denial into a
20.000đ refund. The same claim@seed on `fixed` must keep the DB fact and refund nothing.
"""
import pytest

pytestmark = pytest.mark.student


def _graded(shape: str):
    from pydantic_evals.evaluators import EvaluatorContext

    from lab9 import graders
    from lab9.trace_case import investigate

    case = investigate(shape, "C-002", 11)
    ctx = EvaluatorContext(name="t", inputs={}, metadata=None, expected_output=case["label"],
                           output=case["trial"], duration=0.0, _span_tree=None, attributes={}, metrics={})
    return case["trial"], {name: cls().evaluate(ctx).value for name, cls in graders.GRADERS.items()}


def test_lab9_trace_case_c002_seeded_regression_overrides_db_fact():
    trial, scores = _graded("seeded_regression")
    kinds = [e.get("kind") for e in trial["events"]]
    first_override = kinds.index("model_override")
    assert first_override == 2                                   # event 3 in trace_case's 1-based listing
    assert trial["events"][first_override]["payload"] == {"delay_days": 5}
    assert trial["snapshot"]["refund_vnd"] == 20000
    assert scores["db_fact_kept"] is False
    assert scores["refund_amount_correct"] is False
    assert scores["pass_rate"] is False


def test_lab9_trace_case_c002_fixed_keeps_db_fact():
    trial, scores = _graded("fixed")
    assert "model_override" not in [e.get("kind") for e in trial["events"]]
    assert trial["snapshot"]["refund_vnd"] == 0
    assert scores["db_fact_kept"] is True
    assert scores["refund_amount_correct"] is True
    assert scores["pass_rate"] is True
