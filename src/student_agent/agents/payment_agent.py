from __future__ import annotations

from typing import Any

from ..mcp_gateway import EvidenceGateway
from ..state import CaseState
from ..trace import TraceWriter
from .base import BaseAgent


class PaymentAgent(BaseAgent):
    """Specialist Agent for Payments, Transactions, Gateways, and Refunds."""

    def __init__(self) -> None:
        super().__init__(
            name="payment_agent",
            allowed_tools={"get_order_payments", "get_payment_timeline", "get_refund_timeline"},
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
            state.payment_verdict = "insufficient_evidence"
            state.captured_total_brl = None
            state.refunded_total_brl = None
            state.refundable_total_brl = None
            return

        captured_sum = 0.0
        refunded_sum = 0.0
        has_payments = False
        refund_status: str | None = None
        duplicate_detected = False

        for order_id in target_orders:
            # 1. Fetch payments
            pay_ev = await self.call_tool_cached(
                gateway, "get_order_payments", case_id, trace, state, cache, order_id=order_id
            )
            if pay_ev and "data" in pay_ev:
                pdata = pay_ev["data"]
                pay_rows = pdata if isinstance(pdata, list) else pdata.get("payments", [])
                seen_payments: set[tuple[str, float]] = set()

                for prow in pay_rows:
                    if isinstance(prow, dict):
                        has_payments = True
                        pref = str(
                            prow.get("payment_reference")
                            or prow.get("payment_id")
                            or f"{order_id}_{prow.get('payment_sequential', 1)}"
                        )
                        if pref and pref not in state.payment_references:
                            state.payment_references.append(pref)

                        val = float(prow.get("payment_value") or 0.0)
                        ptype = str(prow.get("payment_type") or "")
                        # Check duplicate
                        key = (ptype, round(val, 2))
                        if key in seen_payments and ptype != "voucher":
                            duplicate_detected = True
                        seen_payments.add(key)

                        captured_sum += val

            # 2. Fetch payment timeline
            await self.call_tool_cached(
                gateway, "get_payment_timeline", case_id, trace, state, cache, order_id=order_id
            )

            # 3. Fetch refund timeline
            refund_ev = await self.call_tool_cached(
                gateway, "get_refund_timeline", case_id, trace, state, cache, order_id=order_id
            )
            if refund_ev and "data" in refund_ev:
                rdata = refund_ev["data"]
                refund_events = rdata if isinstance(rdata, list) else rdata.get("refunds", [])
                for rev in refund_events:
                    if isinstance(rev, dict):
                        r_amt = float(rev.get("amount") or rev.get("refund_amount") or 0.0)
                        r_stat = str(rev.get("status") or "").lower()
                        if r_stat in {"succeeded", "completed", "refunded"}:
                            refunded_sum += r_amt
                        elif r_stat in {"pending", "processing"}:
                            refund_status = "refund_pending"
                        elif r_stat in {"failed", "rejected"}:
                            refund_status = "refund_failed"

        if not has_payments:
            state.payment_verdict = "insufficient_evidence"
            state.captured_total_brl = None
            state.refunded_total_brl = None
            state.refundable_total_brl = None
            return

        captured_total = round(captured_sum, 2)
        refunded_total = round(refunded_sum, 2)
        refundable_total = max(0.0, round(captured_total - refunded_total, 2))

        state.captured_total_brl = captured_total
        state.refunded_total_brl = refunded_total
        state.refundable_total_brl = refundable_total

        # Verdict assignment
        if refund_status == "refund_failed":
            state.payment_verdict = "refund_failed"
        elif refund_status == "refund_pending":
            state.payment_verdict = "refund_pending"
        elif duplicate_detected:
            state.payment_verdict = "duplicate_capture"
        elif refunded_total >= captured_total and captured_total > 0:
            state.payment_verdict = "refunded"
        else:
            state.payment_verdict = "reconciled"
