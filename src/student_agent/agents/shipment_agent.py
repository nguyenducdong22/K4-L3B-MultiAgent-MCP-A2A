from __future__ import annotations

from typing import Any

from ..mcp_gateway import EvidenceGateway
from ..state import CaseState
from ..trace import TraceWriter
from .base import BaseAgent


class ShipmentAgent(BaseAgent):
    """Specialist Agent for Shipment, Logistics, Carrier Events, and Delay Attribution."""

    def __init__(self) -> None:
        super().__init__(
            name="shipment_agent",
            allowed_tools={"get_shipment_summary"},
        )

    async def investigate(
        self,
        gateway: EvidenceGateway,
        trace: TraceWriter,
        state: CaseState,
        cache: dict[tuple[str, tuple[tuple[str, str], ...]], dict[str, Any]],
    ) -> None:
        case_id = state.case_id
        target_orders = state.resolved_order_ids

        if not target_orders:
            state.shipment_verdict = "insufficient_evidence"
            state.timeline_complete = False
            return

        for order_id in target_orders:
            ev = await self.call_tool_cached(
                gateway, "get_shipment_summary", case_id, trace, state, cache, order_id=order_id
            )
            if not ev or "data" not in ev:
                state.shipment_verdict = "insufficient_evidence"
                state.timeline_complete = False
                continue

            sdata = ev["data"]
            if not isinstance(sdata, dict):
                continue

            state.shipment_data.update(sdata)

            shipment_id = sdata.get("shipment_id") or sdata.get("tracking_number") or order_id
            if shipment_id and shipment_id not in state.shipment_ids:
                state.shipment_ids.append(str(shipment_id))

            # Timestamps
            shipping_limit = sdata.get("shipping_limit_date")
            delivered_carrier = sdata.get("order_delivered_carrier_date")
            delivered_customer = sdata.get("order_delivered_customer_date")
            estimated_delivery = sdata.get("order_estimated_delivery_date")
            status = str(sdata.get("status") or state.order_status).lower()

            late_sellers = sdata.get("late_seller_ids") or []
            if isinstance(late_sellers, list):
                for sid in late_sellers:
                    if sid and sid not in state.late_seller_ids:
                        state.late_seller_ids.append(str(sid))

            timeline_complete = bool(
                shipping_limit and delivered_carrier and delivered_customer and estimated_delivery
            )
            state.timeline_complete = timeline_complete

            if status in {"lost", "missing"}:
                state.shipment_verdict = "lost"
            elif status in {"returned", "return_to_sender"}:
                state.shipment_verdict = "returned"
            elif (
                delivered_carrier
                and shipping_limit
                and delivered_carrier > shipping_limit
            ):
                state.shipment_verdict = "seller_delay"
                if state.seller_ids:
                    for sid in state.seller_ids:
                        if sid not in state.late_seller_ids:
                            state.late_seller_ids.append(sid)
            elif (
                delivered_customer
                and estimated_delivery
                and delivered_customer > estimated_delivery
            ):
                state.shipment_verdict = "logistics_delay"
            elif (
                delivered_customer
                and estimated_delivery
                and delivered_customer <= estimated_delivery
            ):
                state.shipment_verdict = "on_time"
            else:
                if state.order_status in {"canceled", "unavailable"}:
                    is_canceled = state.order_status == "canceled"
                    state.shipment_verdict = "returned" if is_canceled else "insufficient_evidence"
                else:
                    state.shipment_verdict = (
                        "on_time" if delivered_customer else "insufficient_evidence"
                    )
