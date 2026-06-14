"""Unit tests for the Director workflow library."""

from __future__ import annotations

import pytest

from orchestration.workflows import WORKFLOWS, get_workflow
from schemas.director import Domain


def test_termination_review_sequence():
    assert get_workflow("TERMINATION_REVIEW") == [Domain.ER, Domain.LEGAL]


def test_get_workflow_returns_a_copy():
    seq = get_workflow("REORG_RIF")
    seq.append(Domain.CB)
    assert get_workflow("REORG_RIF") == WORKFLOWS["REORG_RIF"]  # original unchanged


def test_unknown_workflow_raises():
    with pytest.raises(KeyError, match="Unknown workflow"):
        get_workflow("NOPE")


def test_all_workflows_are_nonempty_domain_lists():
    for name, sequence in WORKFLOWS.items():
        assert sequence, f"{name} is empty"
        assert all(isinstance(d, Domain) for d in sequence)
