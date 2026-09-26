from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from student_agent.contracts import Contracts
from student_agent.trace import TraceWriter
from student_agent.workflow import solve_case


def test_workflow_produces_valid_contract_output(tmp_path: Path) -> None:
    async def _run() -> None:
        root = Path(__file__).resolve().parents[1]
        contracts = Contracts(root / "contracts" / "schemas")
        trace_file = tmp_path / "trace.jsonl"
        trace = TraceWriter(trace_file, contracts)

        # Mock EvidenceGateway
        gateway = MagicMock()

        async def mock_call(tool_name: str, *, case_id: str, **arguments: str) -> dict[str, Any]:
            if tool_name == "get_order":
                return {
                    "schema_version": "day09-mcp-evidence-v1",
                    "evidence_ref": "ev_0123456789abcdef0123456789",
                    "result_hash": f"sha256:{'0'*64}",
                    "domain": "order",
                    "data": {
                        "order_id": arguments.get("order_id", "TEST_ORD_01"),
                        "order_status": "delivered",
                        "customer_id": "cust_01",
                    },
                }
            elif tool_name == "get_order_items":
                return {
                    "schema_version": "day09-mcp-evidence-v1",
                    "evidence_ref": "ev_items_123456789abcdef0123456",
                    "result_hash": f"sha256:{'1'*64}",
                    "domain": "item",
                    "data": [
                        {"order_item_id": "item_01", "seller_id": "seller_01", "price": 50.0}
                    ],
                }
            elif tool_name == "get_shipment_summary":
                return {
                    "schema_version": "day09-mcp-evidence-v1",
                    "evidence_ref": "ev_shipment_123456789abcdef012",
                    "result_hash": f"sha256:{'2'*64}",
                    "domain": "shipment",
                    "data": {
                        "shipping_limit_date": "2023-01-05T00:00:00Z",
                        "order_delivered_carrier_date": "2023-01-04T00:00:00Z",
                        "order_delivered_customer_date": "2023-01-08T00:00:00Z",
                        "order_estimated_delivery_date": "2023-01-10T00:00:00Z",
                    },
                }
            elif tool_name == "get_order_payments":
                return {
                    "schema_version": "day09-mcp-evidence-v1",
                    "evidence_ref": "ev_payments_123456789abcdef012",
                    "result_hash": f"sha256:{'3'*64}",
                    "domain": "payment",
                    "data": [
                        {
                            "payment_sequential": 1,
                            "payment_type": "credit_card",
                            "payment_value": 50.0,
                        }
                    ],
                }
            elif tool_name == "get_policy":
                return {
                    "schema_version": "day09-mcp-evidence-v1",
                    "evidence_ref": "ev_policy_123456789abcdef0123",
                    "result_hash": f"sha256:{'4'*64}",
                    "domain": "policy",
                    "data": {"policy_id": "standard_sla_v1"},
                }
            return {
                "schema_version": "day09-mcp-evidence-v1",
                "evidence_ref": f"ev_{tool_name[:10]}_123456789abcdef01",
                "result_hash": f"sha256:{'5'*64}",
                "domain": "order",
                "data": {},
            }

        gateway.call = AsyncMock(side_effect=mock_call)

        case = {
            "case_id": "TEST_CASE_001",
            "order_id": "TEST_ORD_01",
            "candidates": ["TEST_ORD_01"],
        }

        output = await solve_case(case, gateway, trace)

        # Validate output schema
        contracts.validate_output(output, "test output")

        # Validate trace schema
        assert trace_file.exists()
        raw_lines = trace_file.read_text(encoding="utf-8").splitlines()
        trace_events = [json.loads(line) for line in raw_lines]
        assert len(trace_events) > 0
        for evt in trace_events:
            contracts.validate_trace(evt, "trace test")

        # Check key output properties
        assert output["schema_version"] == "day09-l3b-output-v2"
        assert output["case_id"] == "TEST_CASE_001"
        assert output["entity_resolution"]["status"] == "resolved"

    asyncio.run(_run())
