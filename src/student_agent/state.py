from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CaseState:
    """State contract passed across specialist agents during case investigation."""

    case_id: str
    raw_case: dict[str, Any]

    # Entity resolution
    entity_status: str = "not_found"  # "resolved" | "ambiguous" | "not_found"
    resolved_order_ids: list[str] = field(default_factory=list)
    rejected_candidates: list[str] = field(default_factory=list)
    entity_confidence: float = 1.0

    # Customer context
    customer_unique_id: str | None = None
    related_order_ids: list[str] = field(default_factory=list)

    # Order and item domain
    order_data: dict[str, Any] = field(default_factory=dict)
    item_ids: list[str] = field(default_factory=list)
    seller_ids: list[str] = field(default_factory=list)
    product_ids: list[str] = field(default_factory=list)
    order_status: str = "unknown"

    # Shipment domain
    shipment_ids: list[str] = field(default_factory=list)
    shipment_verdict: str = "insufficient_evidence"
    late_seller_ids: list[str] = field(default_factory=list)
    timeline_complete: bool = False
    shipment_data: dict[str, Any] = field(default_factory=dict)

    # Payment domain
    payment_references: list[str] = field(default_factory=list)
    payment_verdict: str = "insufficient_evidence"
    captured_total_brl: float | None = 0.0
    refunded_total_brl: float | None = 0.0
    refundable_total_brl: float | None = 0.0
    payment_data: dict[str, Any] = field(default_factory=dict)

    # Policy and decision
    primary_issue: str = "insufficient_evidence"
    secondary_issues: list[str] = field(default_factory=list)
    # "action_required" | "no_action" | "needs_investigation"
    case_status: str = "needs_investigation"
    assessment_confidence: float = 0.95
    claim_assessments: list[dict[str, Any]] = field(default_factory=list)
    data_conflicts: list[dict[str, Any]] = field(default_factory=list)
    ranked_causes: list[dict[str, Any]] = field(default_factory=list)
    responsible_parties: list[dict[str, Any]] = field(default_factory=list)

    # Financial resolution
    recommended_refund_brl: float = 0.0
    refund_lines: list[dict[str, Any]] = field(default_factory=list)
    resolution_actions: list[str] = field(default_factory=list)

    # Audit & Provenance
    evidence_refs: list[str] = field(default_factory=list)

    def add_evidence(self, ref: str | None) -> None:
        if ref and ref not in self.evidence_refs:
            self.evidence_refs.append(ref)
