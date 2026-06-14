"""LangGraph orchestration graph.

Wires the nine agents into a single workflow that enforces the architectural
guarantees structurally:

  - The Director is the entry node; conditional edges route to sub-agents based
    on domain classification.
  - The ER Agent has a mandatory pre-node — Module B (``ERComplianceModule``,
    synchronous, no LLM). Module A (the LLM node) runs only if Module B returns
    CLEAR; HARD_STOP bypasses Module A entirely (Constraint #4).
  - Legal Agent outputs always carry the watermark; the graph asserts it is
    present and never strips it.
  - Any MANDATORY result (ER HARD_STOP, Legal LOW confidence, a PII boundary
    violation) routes to the HITL gate, which notifies the approver and then
    suspends the graph via ``interrupt_after``. The workflow resumes only when
    the external workflow system posts an approval (Constraint #5: the approval
    provenance is written by the workflow, not by any agent).

State is kept JSON-native (models are stored as ``model_dump(mode="json")``) so
it round-trips cleanly through the checkpointer used for HITL suspension.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from adapters.base.audit_log import AuditEntry
from agents.analytics.agent import PeopleAnalyticsAgent
from agents.base.agent import BaseAgent
from agents.cb.agent import CBAgent
from agents.director.agent import DirectorAgent
from agents.er.agent import ERAgent
from agents.hr_ops.agent import HROpsAgent
from agents.hrbp.agent import HRBPAgent
from agents.ld.agent import LDAgent
from agents.legal.agent import LegalAgent
from agents.ta.agent import TAAgent
from schemas.common import AgentRequest, AgentResponse, HITLTier
from schemas.director import Domain


@dataclass
class AgentRegistry:
    """The nine agents the graph orchestrates."""

    director: DirectorAgent
    er: ERAgent
    legal: LegalAgent
    cb: CBAgent
    ld: LDAgent
    hrbp: HRBPAgent
    hr_ops: HROpsAgent
    ta: TAAgent
    analytics: PeopleAnalyticsAgent


def build_registry(**adapter_overrides) -> AgentRegistry:
    """Construct all nine agents (adapters resolve via the factory by default).

    ``adapter_overrides`` (e.g. ``audit_log=...``, ``storage=...``) are passed to
    every agent, which is handy for sharing one set of LOCAL adapters in tests.
    """
    return AgentRegistry(
        director=DirectorAgent(**adapter_overrides),
        er=ERAgent(**adapter_overrides),
        legal=LegalAgent(**adapter_overrides),
        cb=CBAgent(**adapter_overrides),
        ld=LDAgent(**adapter_overrides),
        hrbp=HRBPAgent(**adapter_overrides),
        hr_ops=HROpsAgent(**adapter_overrides),
        ta=TAAgent(**adapter_overrides),
        analytics=PeopleAnalyticsAgent(**adapter_overrides),
    )


class WorkflowState(TypedDict, total=False):
    request: dict                  # AgentRequest.model_dump(mode="json")
    routing: Optional[dict]        # RoutingDecision.model_dump(mode="json")
    pending: list[str]             # remaining Domain values to run
    responses: list[dict]          # AgentResponse dumps, in order
    final: Optional[dict]          # the response the workflow concluded with
    error: Optional[str]
    hitl_pending: bool
    hitl_entry_id: Optional[str]   # audit entry the approval will attach to
    er_clear: bool                 # Module B verdict passthrough
    approval: Optional[dict]       # {"approver_id": ...} posted on resume


# Domain value -> graph node that handles it. ER enters via its Module B node.
NODE_FOR_DOMAIN: dict[str, str] = {
    Domain.ER.value: "er_compliance",
    Domain.LEGAL.value: "legal",
    Domain.CB.value: "cb",
    Domain.LD.value: "ld",
    Domain.HRBP.value: "hrbp",
    Domain.HR_OPS.value: "hr_ops",
    Domain.TA.value: "ta",
    Domain.ANALYTICS.value: "analytics",
}

# Sub-agent nodes driven through BaseAgent.handle(): node name -> Domain value.
# (ER is handled separately via its Module B / Module A nodes.)
_SIMPLE_AGENTS: dict[str, str] = {
    "legal": Domain.LEGAL.value,
    "cb": Domain.CB.value,
    "ld": Domain.LD.value,
    "hrbp": Domain.HRBP.value,
    "hr_ops": Domain.HR_OPS.value,
    "ta": Domain.TA.value,
    "analytics": Domain.ANALYTICS.value,
}


def _request_of(state: WorkflowState) -> AgentRequest:
    return AgentRequest.model_validate(state["request"])


def build_graph(registry: AgentRegistry, checkpointer=None):
    """Build and compile the orchestration graph."""

    director = registry.director

    # ---- entry: PII gate + Director routing ----------------------------
    async def entry(state: WorkflowState) -> dict:
        request = _request_of(state)

        pii = director.pii_detector.scan(request.model_dump())
        if pii.detected:
            await director._log_pii_violation(request, pii)
            response = AgentResponse(
                request_id=request.request_id,
                agent_id="DIRECTOR_AGENT",
                error="PII_BOUNDARY_VIOLATION",
                detail=pii.summary,
                hitl_tier=HITLTier.MANDATORY,
                requires_human_decision=True,
            )
            return {
                "error": "PII_BOUNDARY_VIOLATION",
                "final": response.model_dump(mode="json"),
                "responses": [response.model_dump(mode="json")],
                "pending": [],
                "hitl_pending": False,
            }

        decision = await director.route(request)
        await director.audit_log.append(
            AuditEntry(
                event_type="WORKFLOW_ROUTED",
                agent_id="DIRECTOR_AGENT",
                request_id=request.request_id,
                routing_id=decision.routing_id,
                jurisdiction=request.jurisdiction_code.value,
                detail=f"-> {decision.target_domain.value}",
            )
        )
        request.routing_id = decision.routing_id
        pending = [d.value for d in (decision.sequence or [decision.target_domain])]
        return {
            "request": request.model_dump(mode="json"),
            "routing": decision.model_dump(mode="json"),
            "pending": pending,
            "responses": [],
            "error": None,
            "hitl_pending": False,
        }

    # ---- dispatch: passthrough; conditional edges decide the next node --
    async def dispatch(state: WorkflowState) -> dict:
        return {}

    def route_next(state: WorkflowState) -> str:
        if state.get("error"):
            return "finalize"
        if state.get("hitl_pending"):
            return "hitl_gate"
        pending = state.get("pending") or []
        if not pending:
            return "finalize"
        return NODE_FOR_DOMAIN[pending[0]]

    # ---- ER Module B (deterministic) -----------------------------------
    async def er_compliance(state: WorkflowState) -> dict:
        request = _request_of(state)
        payload = registry.er.parse_payload(request)
        result = await registry.er.run_module_b(request, payload)

        if result.result == "HARD_STOP":
            response = registry.er.hard_stop_response(request, result)
            # HARD_STOP => notify the approver at the source (CHRO escalation).
            await registry.er._notify_hitl(request, response)
            responses = state.get("responses", []) + [response.model_dump(mode="json")]
            return {
                "responses": responses,
                "final": response.model_dump(mode="json"),
                "pending": [],
                "er_clear": False,
                "hitl_pending": True,
                "hitl_entry_id": None,
            }
        return {"er_clear": True}

    def er_branch(state: WorkflowState) -> str:
        return "er_reason" if state.get("er_clear") else "dispatch"

    # ---- ER Module A (LLM) ---------------------------------------------
    async def er_reason(state: WorkflowState) -> dict:
        request = _request_of(state)
        payload = registry.er.parse_payload(request)
        response = await registry.er.run_module_a(request, payload)
        responses = state.get("responses", []) + [response.model_dump(mode="json")]
        pending = [d for d in state.get("pending", []) if d != Domain.ER.value]
        return {
            "responses": responses,
            "final": response.model_dump(mode="json"),
            "pending": pending,
        }

    # ---- generic sub-agent node (driven through handle()) --------------
    def make_agent_node(agent: BaseAgent, domain_value: str):
        async def node(state: WorkflowState) -> dict:
            request = _request_of(state)
            response = await agent.handle(request)

            # The Legal Agent's watermark must survive orchestration.
            if (
                domain_value == Domain.LEGAL.value
                and "WATERMARKED" not in response.jurisdiction_flags
            ):
                raise RuntimeError(
                    "Legal opinion lost its watermark in orchestration"
                )

            responses = state.get("responses", []) + [response.model_dump(mode="json")]
            pending = [d for d in state.get("pending", []) if d != domain_value]
            update: dict = {
                "responses": responses,
                "final": response.model_dump(mode="json"),
                "pending": pending,
            }
            if response.hitl_tier == HITLTier.MANDATORY:
                # handle() already notified; just flag for the HITL gate.
                update["hitl_pending"] = True
                update["pending"] = []
            return update

        return node

    # ---- HITL gate: audit the pending approval, then suspend -----------
    async def hitl_gate(state: WorkflowState) -> dict:
        request = _request_of(state)
        final = AgentResponse.model_validate(state["final"])
        entry_id = await director.audit_log.append(
            AuditEntry(
                event_type="HITL_PENDING",
                agent_id=final.agent_id,
                request_id=request.request_id,
                jurisdiction=request.jurisdiction_code.value,
                hitl_required=True,
                detail=final.hitl_basis,
            )
        )
        return {"hitl_entry_id": entry_id, "hitl_pending": True}

    # ---- finalize: record approval (if any) and complete ---------------
    async def finalize(state: WorkflowState) -> dict:
        request = _request_of(state)
        approval = state.get("approval")
        entry_id = state.get("hitl_entry_id")
        if approval and entry_id:
            # Constraint #5: the workflow system writes approval provenance.
            await director.audit_log.record_approval(
                entry_id, approver_id=approval["approver_id"]
            )
        await director.audit_log.append(
            AuditEntry(
                event_type="WORKFLOW_COMPLETED",
                request_id=request.request_id,
                jurisdiction=request.jurisdiction_code.value,
                detail="approved" if approval else "completed",
            )
        )
        return {}

    graph = StateGraph(WorkflowState)
    graph.add_node("entry", entry)
    graph.add_node("dispatch", dispatch)
    graph.add_node("er_compliance", er_compliance)
    graph.add_node("er_reason", er_reason)
    for node_name, domain_value in _SIMPLE_AGENTS.items():
        agent = getattr(registry, node_name)
        graph.add_node(node_name, make_agent_node(agent, domain_value))
    graph.add_node("hitl_gate", hitl_gate)
    graph.add_node("finalize", finalize)

    graph.set_entry_point("entry")
    graph.add_edge("entry", "dispatch")
    graph.add_conditional_edges(
        "dispatch",
        route_next,
        {
            "er_compliance": "er_compliance",
            "legal": "legal",
            "cb": "cb",
            "ld": "ld",
            "hrbp": "hrbp",
            "hr_ops": "hr_ops",
            "ta": "ta",
            "analytics": "analytics",
            "hitl_gate": "hitl_gate",
            "finalize": "finalize",
        },
    )
    graph.add_conditional_edges(
        "er_compliance", er_branch, {"er_reason": "er_reason", "dispatch": "dispatch"}
    )
    graph.add_edge("er_reason", "dispatch")
    for node_name in _SIMPLE_AGENTS:
        graph.add_edge(node_name, "dispatch")
    graph.add_edge("hitl_gate", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile(
        checkpointer=checkpointer or MemorySaver(),
        interrupt_after=["hitl_gate"],
    )


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


async def run_workflow(graph, request: AgentRequest, thread_id: str = "default") -> dict:
    """Run a request through the graph. Returns the (possibly suspended) state."""
    return await graph.ainvoke(
        {"request": request.model_dump(mode="json")}, _config(thread_id)
    )


async def resume_with_approval(graph, thread_id: str, approver_id: str) -> dict:
    """Post a human approval into a suspended workflow and resume it."""
    config = _config(thread_id)
    await graph.aupdate_state(config, {"approval": {"approver_id": approver_id}})
    return await graph.ainvoke(None, config)


__all__ = [
    "AgentRegistry",
    "build_registry",
    "build_graph",
    "run_workflow",
    "resume_with_approval",
    "WorkflowState",
]
