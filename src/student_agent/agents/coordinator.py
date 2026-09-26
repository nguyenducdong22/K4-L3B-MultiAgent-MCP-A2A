from __future__ import annotations

from typing import Any

from ..mcp_gateway import EvidenceGateway
from ..state import CaseState
from ..trace import TraceWriter
from .base import BaseAgent


class CoordinatorAgent(BaseAgent):
    """Coordinator and Router: handles entity resolution, candidate pruning, and agent handoffs."""

    def __init__(self) -> None:
        super().__init__(
            name="coordinator",
            allowed_tools={"get_order", "get_customer_history"},
        )

    async def resolve_entities(
        self,
        gateway: EvidenceGateway,
        trace: TraceWriter,
        state: CaseState,
        cache: dict[tuple[str, tuple[tuple[str, str], ...]], dict[str, Any]],
    ) -> None:
        raw = state.raw_case
        case_id = state.case_id

        trace.emit(
            case_id=case_id,
            event_type="task_assigned",
            actor=self.name,
            target="coordinator",
            attributes={"task": "entity_resolution"},
        )

        candidates: list[str] = []
        if "order_id" in raw and raw["order_id"]:
            candidates.append(str(raw["order_id"]))
        if "candidate_order_ids" in raw and isinstance(raw["candidate_order_ids"], list):
            candidates.extend(str(cid) for cid in raw["candidate_order_ids"])
        if "candidates" in raw and isinstance(raw["candidates"], list):
            candidates.extend(str(cid) for cid in raw["candidates"])

        req = raw.get("customer_request")
        if isinstance(req, dict):
            claimed = req.get("claimed_order_id")
            if claimed and str(claimed) not in candidates:
                candidates.append(str(claimed))

        # Deduplicate candidates while preserving order
        unique_candidates: list[str] = []
        for c in candidates:
            if c not in unique_candidates:
                unique_candidates.append(c)

        customer_unique_id = (
            raw.get("customer_unique_id")
            or raw.get("customer_unique_id_hint")
            or raw.get("customer_id")
        )
        if not customer_unique_id and isinstance(req, dict):
            customer_unique_id = req.get("customer_unique_id") or req.get("customer_id")
        if customer_unique_id:
            state.customer_unique_id = str(customer_unique_id)
            cust_ev = await self.call_tool_cached(
                gateway,
                "get_customer_history",
                case_id,
                trace,
                state,
                cache,
                customer_unique_id=state.customer_unique_id,
            )
            if cust_ev and "data" in cust_ev:
                cust_data = cust_ev["data"]
                if isinstance(cust_data, dict):
                    orders = cust_data.get("orders") or cust_data.get("related_order_ids") or []
                    if isinstance(orders, list):
                        for ord_entry in orders:
                            ord_id = (
                                ord_entry.get("order_id")
                                if isinstance(ord_entry, dict)
                                else str(ord_entry)
                            )
                            if ord_id and ord_id not in state.related_order_ids:
                                state.related_order_ids.append(ord_id)

        # Probe candidate orders against MCP
        valid_orders: list[str] = []
        rejected: list[str] = []

        for candidate_id in unique_candidates:
            ev = await self.call_tool_cached(
                gateway, "get_order", case_id, trace, state, cache, order_id=candidate_id
            )
            if ev and ev.get("data"):
                valid_orders.append(candidate_id)
            else:
                rejected.append(candidate_id)

        state.rejected_candidates = rejected

        if len(valid_orders) == 1:
            state.entity_status = "resolved"
            state.resolved_order_ids = valid_orders
            state.entity_confidence = 1.0
        elif len(valid_orders) > 1:
            state.entity_status = "ambiguous"
            state.resolved_order_ids = valid_orders
            state.entity_confidence = 0.6
        elif unique_candidates:
            state.entity_status = "not_found"
            state.resolved_order_ids = unique_candidates[:1]
            state.entity_confidence = 0.3
        else:
            state.entity_status = "not_found"
            state.resolved_order_ids = []
            state.entity_confidence = 0.0
