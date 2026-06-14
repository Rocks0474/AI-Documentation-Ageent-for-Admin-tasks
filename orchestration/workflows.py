"""Director workflow library — pre-built sequential patterns.

Some HR situations always touch the same agents in the same order. These named
workflows let the Director (or an operator) seed a known sequence instead of
relying on single-domain classification. Each workflow is an ordered list of
:class:`Domain` steps the orchestration graph executes in turn.
"""

from __future__ import annotations

from schemas.director import Domain

# Named, ordered multi-agent patterns.
WORKFLOWS: dict[str, list[Domain]] = {
    # A potential termination: ER assesses, Legal opines.
    "TERMINATION_REVIEW": [Domain.ER, Domain.LEGAL],
    # A reduction in force: understand the population, ER process, legal review.
    "REORG_RIF": [Domain.ANALYTICS, Domain.ER, Domain.LEGAL],
    # Compensation review with a legal cross-check (e.g. pay equity).
    "PAY_EQUITY_REVIEW": [Domain.ANALYTICS, Domain.CB, Domain.LEGAL],
    # New hire onboarding: comp offer then HR operations setup.
    "OFFER_AND_ONBOARD": [Domain.CB, Domain.HR_OPS],
    # Capability building: identify the gap, then build the learning path.
    "SKILLS_UPLIFT": [Domain.ANALYTICS, Domain.LD],
}


def get_workflow(name: str) -> list[Domain]:
    """Return a copy of the named workflow's domain sequence.

    Raises ``KeyError`` if the workflow is not defined.
    """
    if name not in WORKFLOWS:
        raise KeyError(
            f"Unknown workflow {name!r}. Known: {', '.join(sorted(WORKFLOWS))}."
        )
    return list(WORKFLOWS[name])
