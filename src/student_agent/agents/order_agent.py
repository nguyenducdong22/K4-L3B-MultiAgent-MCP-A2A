from __future__ import annotations

from typing import Any

from ..mcp_gateway import EvidenceGateway
from ..state import CaseState
from ..trace import TraceWriter
from .base import BaseAgent


class OrderAgent(BaseAgent):
    """Specialist Agent for Order, Items, Sellers, and Product Context."""

    def __init__(self) -> None:
        super().__init__(
            name="order_agent",
            allowed_tools={"get_order", "get_order_items", "get_sellers", "get_product_context"},
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
            return

        for order_id in target_orders:
            # 1. Fetch order details
            order_ev = await self.call_tool_cached(
                gateway, "get_order", case_id, trace, state, cache, order_id=order_id
            )
            if order_ev and "data" in order_ev:
                odata = order_ev["data"]
                if isinstance(odata, dict):
                    state.order_data.update(odata)
                    state.order_status = str(odata.get("order_status", "unknown")).lower()
                    cust_id = odata.get("customer_id")
                    if cust_id and not state.customer_unique_id:
                        state.customer_unique_id = str(cust_id)

            # 2. Fetch order items
            items_ev = await self.call_tool_cached(
                gateway, "get_order_items", case_id, trace, state, cache, order_id=order_id
            )
            if items_ev and "data" in items_ev:
                idata = items_ev["data"]
                items_list = idata if isinstance(idata, list) else idata.get("items", [])
                for itm in items_list:
                    if isinstance(itm, dict):
                        item_id = str(itm.get("order_item_id") or itm.get("item_id") or "")
                        seller_id = str(itm.get("seller_id") or "")
                        prod_id = str(itm.get("product_id") or "")
                        if item_id and item_id not in state.item_ids:
                            state.item_ids.append(item_id)
                        if seller_id and seller_id not in state.seller_ids:
                            state.seller_ids.append(seller_id)
                        if prod_id and prod_id not in state.product_ids:
                            state.product_ids.append(prod_id)

            # 3. Fetch sellers
            sellers_ev = await self.call_tool_cached(
                gateway, "get_sellers", case_id, trace, state, cache, order_id=order_id
            )
            if sellers_ev and "data" in sellers_ev:
                sdata = sellers_ev["data"]
                s_list = sdata if isinstance(sdata, list) else sdata.get("sellers", [])
                for s in s_list:
                    if isinstance(s, dict):
                        sid = str(s.get("seller_id") or "")
                        if sid and sid not in state.seller_ids:
                            state.seller_ids.append(sid)

            # 4. Fetch product context
            await self.call_tool_cached(
                gateway, "get_product_context", case_id, trace, state, cache, order_id=order_id
            )
