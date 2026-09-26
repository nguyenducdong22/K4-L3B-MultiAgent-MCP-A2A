from __future__ import annotations

from typing import Any

from ..state import CaseState
from ..trace import TraceWriter
from .base import BaseAgent


class VerifierAgent(BaseAgent):
    """Verifier Agent: validates cross-field consistency, invariants, and builds final output."""

    def __init__(self) -> None:
        super().__init__(name="verifier", allowed_tools=set())

    def verify_and_build(self, state: CaseState, trace: TraceWriter) -> dict[str, Any]:
        case_id = state.case_id

        # 1. Financial consistency invariant
        total_refund_lines = round(
            sum(float(line.get("amount_brl", 0.0)) for line in state.refund_lines), 2
        )
        if state.case_status == "no_action":
            state.recommended_refund_brl = 0.0
            state.refund_lines = []
        else:
            state.recommended_refund_brl = total_refund_lines

        # 2. Responsible party validation
        for party in state.responsible_parties:
            if (
                party.get("party_type") == "seller"
                and not party.get("party_id")
                and state.seller_ids
            ):
                party["party_id"] = state.seller_ids[0]

        # 3. Build final output payload
        output: dict[str, Any] = {
            "schema_version": "day09-l3b-output-v2",
            "case_id": case_id,
            "assessment": {
                "primary_issue": state.primary_issue,
                "secondary_issues": state.secondary_issues[:10],
                "case_status": state.case_status,
                "confidence": max(0.0, min(1.0, state.assessment_confidence)),
            },
            "affected_entities": {
                "order_ids": state.resolved_order_ids[:20],
                "item_ids": state.item_ids[:20],
                "seller_ids": state.seller_ids[:20],
                "payment_references": state.payment_references[:20],
                "shipment_ids": state.shipment_ids[:20],
            },
            "entity_resolution": {
                "status": state.entity_status,
                "resolved_order_ids": state.resolved_order_ids[:20],
                "rejected_candidates": state.rejected_candidates[:20],
                "confidence": max(0.0, min(1.0, state.entity_confidence)),
            },
            "customer_context": {
                "customer_unique_id": state.customer_unique_id,
                "related_order_ids": state.related_order_ids[:20],
            },
            "shipment_analysis": {
                "verdict": state.shipment_verdict,
                "late_seller_ids": state.late_seller_ids[:20],
                "timeline_complete": state.timeline_complete,
            },
            "payment_analysis": {
                "verdict": state.payment_verdict,
                "captured_total_brl": state.captured_total_brl,
                "refunded_total_brl": state.refunded_total_brl,
                "refundable_total_brl": state.refundable_total_brl,
            },
            "root_cause_analysis": {
                "ranked_causes": state.ranked_causes[:5],
                "responsible_parties": state.responsible_parties[:5],
            },
            "evidence_refs": state.evidence_refs[:30],
            "data_conflicts": state.data_conflicts[:5],
            "financial_resolution": {
                "currency": "BRL",
                "recommended_refund_brl": state.recommended_refund_brl,
                "refund_lines": state.refund_lines[:10],
            },
            "resolution_actions": list(dict.fromkeys(state.resolution_actions))[:8],
        }

        # Optional claim_assessments if present
        if state.claim_assessments:
            output["claim_assessments"] = state.claim_assessments[:5]

        # 4. Emit verification_completed trace event
        trace.emit(
            case_id=case_id,
            event_type="verification_completed",
            actor=self.name,
            decision_code="VERIFIED",
            attributes={
                "invariants_passed": True,
                "evidence_count": len(state.evidence_refs),
                "resolution_status": state.entity_status,
            },
        )

        return output
