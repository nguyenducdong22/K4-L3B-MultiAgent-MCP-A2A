from __future__ import annotations

from typing import Any

from .agents.coordinator import CoordinatorAgent
from .agents.order_agent import OrderAgent
from .agents.payment_agent import PaymentAgent
from .agents.policy_agent import PolicyAgent
from .agents.shipment_agent import ShipmentAgent
from .agents.verifier_agent import VerifierAgent
from .mcp_gateway import EvidenceGateway
from .state import CaseState
from .trace import TraceWriter


async def solve_case(
    case: dict[str, Any], gateway: EvidenceGateway, trace: TraceWriter
) -> dict[str, Any]:
    """Execute the Day09 L3B Multi-Agent A2A investigation workflow.

    Pipeline:
      Coordinator (Entity Resolution)
        -> OrderAgent (Items, Sellers, Product)
        -> ShipmentAgent (Logistics & Timeline SLA)
        -> PaymentAgent (Captures & Refunds)
        -> PolicyAgent (Policy Rules & Remedies)
        -> Verifier (Invariant Enforcement & Schema Guard)
    """
    case_id = str(case["case_id"])
    state = CaseState(case_id=case_id, raw_case=case)
    mcp_cache: dict[tuple[str, tuple[tuple[str, str], ...]], dict[str, Any]] = {}

    # Initialize Agents
    coordinator = CoordinatorAgent()
    order_agent = OrderAgent()
    shipment_agent = ShipmentAgent()
    payment_agent = PaymentAgent()
    policy_agent = PolicyAgent()
    verifier = VerifierAgent()

    # 1. Coordinator: Entity Resolution & Customer History
    await coordinator.resolve_entities(gateway, trace, state, mcp_cache)

    # 2. Handoff to Order/Item Agent
    trace.emit(
        case_id=case_id,
        event_type="handoff",
        actor=coordinator.name,
        target=order_agent.name,
        attributes={"task": "order_investigation"},
    )
    await order_agent.investigate(gateway, trace, state, mcp_cache)

    # 3. Handoff to Shipment Agent
    trace.emit(
        case_id=case_id,
        event_type="handoff",
        actor=order_agent.name,
        target=shipment_agent.name,
        attributes={"task": "shipment_investigation"},
    )
    await shipment_agent.investigate(gateway, trace, state, mcp_cache)

    # 4. Handoff to Payment Agent
    trace.emit(
        case_id=case_id,
        event_type="handoff",
        actor=shipment_agent.name,
        target=payment_agent.name,
        attributes={"task": "payment_investigation"},
    )
    await payment_agent.investigate(gateway, trace, state, mcp_cache)

    # 5. Handoff to Policy Agent
    trace.emit(
        case_id=case_id,
        event_type="handoff",
        actor=payment_agent.name,
        target=policy_agent.name,
        attributes={"task": "policy_evaluation"},
    )
    await policy_agent.evaluate(gateway, trace, state, mcp_cache)

    # 6. Handoff to Verifier Agent
    trace.emit(
        case_id=case_id,
        event_type="handoff",
        actor=policy_agent.name,
        target=verifier.name,
        attributes={"task": "verification"},
    )
    output = verifier.verify_and_build(state, trace)

    return output
