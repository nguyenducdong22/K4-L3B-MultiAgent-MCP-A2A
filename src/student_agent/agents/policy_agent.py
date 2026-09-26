from __future__ import annotations

from typing import Any

from ..ai_advisor import GroqAdvisor
from ..mcp_gateway import EvidenceGateway
from ..state import CaseState
from ..trace import TraceWriter
from .base import BaseAgent


class PolicyAgent(BaseAgent):
    """Specialist Agent for Policy Application, Root Cause Analysis, and Financial Remedies."""

    def __init__(self) -> None:
        super().__init__(
            name="policy_agent",
            allowed_tools={"get_policy"},
        )

    async def evaluate(
        self,
        gateway: EvidenceGateway,
        trace: TraceWriter,
        state: CaseState,
        cache: dict[tuple[str, tuple[tuple[str, str], ...]], dict[str, Any]],
    ) -> None:
        case_id = state.case_id

        # 1. Fetch policy
        pol_ver = str(state.raw_case.get("policy_version") or "v1")
        await self.call_tool_cached(
            gateway, "get_policy", case_id, trace, state, cache, policy_version=pol_ver
        )

        # 2. Determine Primary and Secondary Issues
        primary_issue = "insufficient_evidence"
        secondary_issues: list[str] = []
        case_status = "needs_investigation"
        confidence = 0.90
        ranked_causes: list[dict[str, Any]] = []
        responsible_parties: list[dict[str, Any]] = []
        recommended_refund = 0.0
        refund_lines: list[dict[str, Any]] = []
        resolution_actions: list[str] = []

        # Logic based on domain evidence
        order_status = state.order_status
        shipment_verdict = state.shipment_verdict
        payment_verdict = state.payment_verdict
        refundable = state.refundable_total_brl or 0.0
        primary_order_id = state.resolved_order_ids[0] if state.resolved_order_ids else None
        primary_seller_id = state.seller_ids[0] if state.seller_ids else None

        if state.entity_status == "not_found":
            primary_issue = "insufficient_evidence"
            case_status = "needs_investigation"
            confidence = 0.85
            ranked_causes = [{"cause_code": "ENTITY_NOT_FOUND", "rank": 1}]
            responsible_parties = [{"party_type": "unknown", "party_id": None}]
            resolution_actions = ["request_customer_clarification"]

        elif order_status == "canceled" and (state.captured_total_brl or 0.0) > 0:
            primary_issue = "canceled_order_paid"
            case_status = "action_required"
            confidence = 0.98
            ranked_causes = [{"cause_code": "CANCELED_BEFORE_FULFILLMENT", "rank": 1}]
            responsible_parties = [
                {"party_type": "platform", "party_id": None},
                {"party_type": "seller", "party_id": primary_seller_id},
            ]
            recommended_refund = refundable
            if recommended_refund > 0:
                refund_lines.append({
                    "reason_code": "REFUND_CANCELED_ORDER",
                    "amount_brl": round(recommended_refund, 2),
                    "entity_id": primary_order_id,
                })
            resolution_actions = ["issue_full_refund", "notify_customer"]

        elif order_status == "unavailable" and (state.captured_total_brl or 0.0) > 0:
            primary_issue = "unavailable_order_paid"
            case_status = "action_required"
            confidence = 0.98
            ranked_causes = [{"cause_code": "ITEM_OUT_OF_STOCK", "rank": 1}]
            responsible_parties = [{"party_type": "seller", "party_id": primary_seller_id}]
            recommended_refund = refundable
            if recommended_refund > 0:
                refund_lines.append({
                    "reason_code": "REFUND_UNAVAILABLE_ITEM",
                    "amount_brl": round(recommended_refund, 2),
                    "entity_id": primary_order_id,
                })
            resolution_actions = ["issue_full_refund", "notify_seller_inventory"]

        elif payment_verdict == "refund_failed":
            primary_issue = "refund_failed"
            case_status = "action_required"
            confidence = 0.95
            ranked_causes = [{"cause_code": "GATEWAY_REFUND_REJECTED", "rank": 1}]
            responsible_parties = [{"party_type": "payment_provider", "party_id": None}]
            recommended_refund = refundable
            if recommended_refund > 0:
                refund_lines.append({
                    "reason_code": "RETRY_REFUND",
                    "amount_brl": round(recommended_refund, 2),
                    "entity_id": primary_order_id,
                })
            resolution_actions = ["retry_refund_transaction", "notify_finance"]

        elif payment_verdict == "refund_pending":
            primary_issue = "refund_pending"
            case_status = "no_action"
            confidence = 0.92
            ranked_causes = [{"cause_code": "REFUND_PROCESSING_WINDOW", "rank": 1}]
            responsible_parties = [{"party_type": "payment_provider", "party_id": None}]
            resolution_actions = ["monitor_refund_status", "inform_customer_timeline"]

        elif payment_verdict == "duplicate_capture":
            primary_issue = "duplicate_charge"
            case_status = "action_required"
            confidence = 0.95
            ranked_causes = [{"cause_code": "DUPLICATE_PAYMENT_PROCESSED", "rank": 1}]
            responsible_parties = [{"party_type": "payment_provider", "party_id": None}]
            # Refund duplicate portion
            dup_amount = round(refundable / 2.0, 2) if refundable > 0 else 0.0
            recommended_refund = dup_amount
            if recommended_refund > 0:
                refund_lines.append({
                    "reason_code": "REFUND_DUPLICATE_CHARGE",
                    "amount_brl": recommended_refund,
                    "entity_id": primary_order_id,
                })
            resolution_actions = ["refund_excess_charge", "notify_customer"]

        elif shipment_verdict == "seller_delay":
            primary_issue = "late_delivery_seller"
            case_status = "action_required"
            confidence = 0.94
            ranked_causes = [{"cause_code": "SELLER_DISPATCH_BREACH", "rank": 1}]
            responsible_parties = [{"party_type": "seller", "party_id": primary_seller_id}]
            resolution_actions = ["penalize_seller_late_fulfillment", "send_apology_voucher"]

        elif shipment_verdict == "logistics_delay":
            primary_issue = "late_delivery_logistics"
            case_status = "no_action"
            confidence = 0.94
            ranked_causes = [{"cause_code": "CARRIER_TRANSIT_DELAY", "rank": 1}]
            responsible_parties = [{"party_type": "logistics_provider", "party_id": None}]
            resolution_actions = ["file_carrier_sla_inquiry", "update_tracking_notes"]

        elif shipment_verdict == "lost":
            primary_issue = "late_delivery_logistics"
            case_status = "action_required"
            confidence = 0.95
            ranked_causes = [{"cause_code": "PACKAGE_LOST_IN_TRANSIT", "rank": 1}]
            responsible_parties = [{"party_type": "logistics_provider", "party_id": None}]
            recommended_refund = refundable
            if recommended_refund > 0:
                refund_lines.append({
                    "reason_code": "REFUND_LOST_PARCEL",
                    "amount_brl": round(recommended_refund, 2),
                    "entity_id": primary_order_id,
                })
            resolution_actions = ["claim_carrier_insurance", "issue_full_refund"]

        elif shipment_verdict == "on_time" and payment_verdict in {"reconciled", "refunded"}:
            primary_issue = "unsupported_claim"
            case_status = "no_action"
            confidence = 0.96
            ranked_causes = [{"cause_code": "FULFILLMENT_SLA_MET", "rank": 1}]
            responsible_parties = [{"party_type": "customer", "party_id": state.customer_unique_id}]
            resolution_actions = ["reject_claim_with_proof", "close_case"]

        else:
            primary_issue = "insufficient_evidence"
            case_status = "needs_investigation"
            confidence = 0.80
            ranked_causes = [{"cause_code": "EVIDENCE_INCONCLUSIVE", "rank": 1}]
            responsible_parties = [{"party_type": "unknown", "party_id": None}]
        # Claim assessments
        req = state.raw_case.get("customer_request")
        if isinstance(req, dict):
            claims = req.get("claims")
            if isinstance(claims, list):
                for clm in claims:
                    if isinstance(clm, dict):
                        cid = str(clm.get("claim_id", ""))
                        topic = str(clm.get("topic", "")).lower()
                        if not cid:
                            continue
                        c_verdict = "insufficient_evidence"
                        c_conf = 0.85
                        if "late" in topic:
                            if state.shipment_verdict in {"seller_delay", "logistics_delay"}:
                                c_verdict = "supported"
                                c_conf = 0.95
                            elif state.shipment_verdict == "on_time":
                                c_verdict = "unsupported"
                                c_conf = 0.95
                        elif "refund" in topic:
                            if recommended_refund > 0:
                                c_verdict = "supported"
                                c_conf = 0.95
                            else:
                                c_verdict = "unsupported"
                                c_conf = 0.90
                        elif "split_payment" in topic:
                            if len(state.payment_references) > 1:
                                c_verdict = "supported"
                                c_conf = 0.95
                            else:
                                c_verdict = "partially_supported"
                                c_conf = 0.85
                        elif state.entity_status == "resolved":
                            c_verdict = (
                                "supported"
                                if primary_issue != "insufficient_evidence"
                                else "insufficient_evidence"
                            )
                        state.claim_assessments.append({
                            "claim_id": cid,
                            "verdict": c_verdict,
                            "confidence": c_conf,
                            "evidence_refs": state.evidence_refs[:10],
                        })

        # AI Advisor enhancement
        advisor = GroqAdvisor()
        msg = req.get("message", "") if isinstance(req, dict) else ""
        if msg:
            advice = await advisor.advise_dispute(
                customer_message=msg,
                primary_issue=primary_issue,
                order_status=state.order_status,
                shipment_verdict=state.shipment_verdict,
                payment_verdict=state.payment_verdict,
            )
            if advice and isinstance(advice, dict):
                ai_sec = advice.get("secondary_issues")
                if isinstance(ai_sec, list):
                    for s in ai_sec:
                        s_str = str(s).strip()[:80]
                        if s_str and s_str not in secondary_issues:
                            secondary_issues.append(s_str)
                ai_act = advice.get("suggested_actions")
                if isinstance(ai_act, list):
                    for a in ai_act:
                        a_str = str(a).strip()[:80]
                        if a_str and a_str not in resolution_actions:
                            resolution_actions.append(a_str)

        # Populate state
        state.primary_issue = primary_issue
        state.secondary_issues = secondary_issues[:10]
        state.case_status = case_status
        state.assessment_confidence = round(confidence, 2)
        state.ranked_causes = ranked_causes[:5]
        state.responsible_parties = responsible_parties[:5]
        state.recommended_refund_brl = round(recommended_refund, 2)
        state.refund_lines = refund_lines[:10]
        if not resolution_actions:
            resolution_actions = ["investigate_case_evidence"]
        state.resolution_actions = list(dict.fromkeys(resolution_actions))[:8]

        trace.emit(
            case_id=case_id,
            event_type="policy_decided",
            actor=self.name,
            decision_code=primary_issue.upper(),
            attributes={"case_status": case_status, "confidence": state.assessment_confidence},
        )
