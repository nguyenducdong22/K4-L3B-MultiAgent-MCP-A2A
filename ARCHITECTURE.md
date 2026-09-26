# L3B Architecture Record

Hệ thống Multi-Agent điều tra tranh chấp TMĐT (E-commerce Dispute Investigation) dựa trên MCP Evidence Gateway và giao thức Agent-to-Agent (A2A).

---

## 1. System overview

Hệ thống hoạt động theo pipeline A2A tuần tự có kiểm soát trạng thái (State Machine), đảm bảo tính giải trình (Auditability), kiểm chứng schema nghiêm ngặt và tối ưu hóa chi phí gọi MCP:

```text
Input Case
    │
    ▼
┌────────────────────────────────────────────────────────┐
│ Coordinator / Router Agent                             │
│ - Parse candidates, probe MCP get_order                │
│ - Resolve / prune entity ambiguity                     │
│ - Query get_customer_history                           │
└──────────────────────────┬─────────────────────────────┘
                           │ (handoff: task="order_investigation")
                           ▼
┌────────────────────────────────────────────────────────┐
│ Order / Item Agent                                     │
│ - Probe items, sellers, product taxonomy context       │
│ - Extract item_ids, seller_ids, order_status           │
└──────────────────────────┬─────────────────────────────┘
                           │ (handoff: task="shipment_investigation")
                           ▼
┌────────────────────────────────────────────────────────┐
│ Shipment Agent                                         │
│ - Query get_shipment_summary                           │
│ - Compare shipping limits vs carrier handoff           │
│ - Determine delay attribution (seller vs logistics)    │
└──────────────────────────┬─────────────────────────────┘
                           │ (handoff: task="payment_investigation")
                           ▼
┌────────────────────────────────────────────────────────┐
│ Payment Agent                                          │
│ - Query get_order_payments, payment & refund timelines │
│ - Calculate captured, refunded, refundable totals      │
│ - Detect duplicate capture, refund status              │
└──────────────────────────┬─────────────────────────────┘
                           │ (handoff: task="policy_evaluation")
                           ▼
┌────────────────────────────────────────────────────────┐
│ Policy Agent                                           │
│ - Query get_policy authoritative rules                 │
│ - Synthesize root causes and responsible parties       │
│ - Calculate financial resolution & resolution actions  │
│ - Emit policy_decided trace event                      │
└──────────────────────────┬─────────────────────────────┘
                           │ (handoff: task="verification")
                           ▼
┌────────────────────────────────────────────────────────┐
│ Verifier Agent                                         │
│ - Enforce invariants (cross-field consistency, schema) │
│ - Validate evidence ownership & calibration            │
│ - Emit verification_completed trace event              │
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼
               [Final Validated Output]
```

---

## 2. Agent ownership

| Actor | Input | Trách nhiệm | Tool permission | Output/handoff |
| --- | --- | --- | --- | --- |
| **Coordinator** | `raw_case` (`case_id`, `candidates`, `customer_id`) | Khởi tạo `CaseState`, giải quyết entity (thẩm định candidate order IDs), truy vấn lịch sử khách hàng, phát `task_assigned`. | `get_order`, `get_customer_history` | `resolved_order_ids`, `rejected_candidates`, handoff sang `OrderAgent`. |
| **Order/Item Agent** | `resolved_order_ids`, `case_id` | Khai thác chi tiết đơn hàng, danh mục sản phẩm, người bán liên kết, xác định trạng thái đơn (`order_status`). | `get_order`, `get_order_items`, `get_sellers`, `get_product_context` | `item_ids`, `seller_ids`, `product_ids`, `order_status`, handoff sang `ShipmentAgent`. |
| **Shipment Agent** | `resolved_order_ids`, `order_status` | Đối chiếu mốc thời gian giao nhận: hạn giao seller (`shipping_limit_date`), ngày giao bưu cục (`delivered_carrier_date`), ngày giao khách (`delivered_customer_date`), ngày dự kiến (`estimated_delivery_date`). | `get_shipment_summary` | `shipment_verdict`, `late_seller_ids`, `timeline_complete`, handoff sang `PaymentAgent`. |
| **Payment Agent** | `resolved_order_ids` | Tính toán đối soát tài chính: tổng tiền đã trừ (`captured_total_brl`), tiền đã hoàn (`refunded_total_brl`), tiền còn có thể hoàn (`refundable_total_brl`), phát hiện duplicate charge hay lỗi hoàn tiền. | `get_order_payments`, `get_payment_timeline`, `get_refund_timeline` | `payment_verdict`, số dư BRL, handoff sang `PolicyAgent`. |
| **Policy Agent** | Toàn bộ bằng chứng domain từ các Agent trước | Đối chiếu điều khoản hoàn tiền và SLA nền tảng, gán `primary_issue`, xếp hạng nguyên nhân gốc rễ (`ranked_causes`), phân định bên chịu trách nhiệm (`responsible_parties`), lập dòng hoàn tiền (`refund_lines`). | `get_policy` | Quyết định bồi thường, `policy_decided`, handoff sang `Verifier`. |
| **Verifier** | `CaseState` đầy đủ | Kiểm tra các bất biến nghiệp vụ, tính toàn vẹn của JSON Schema, khóa chặt format tiền tệ và danh sách `evidence_refs`, phát `verification_completed`. | *None* (Pure verification guard) | `outputs/<case_id>.json` chuẩn contract `day09-l3b-output-v2`. |

---

## 3. Entity resolution và A2A protocol

- **Candidate Resolution**:
  - Coordinator tiếp nhận các ứng viên từ `order_id`, `candidate_order_ids`, `candidates`.
  - Thực hiện thăm dò nhẹ (probe) qua tool thẩm quyền `get_order`. Candidate nào trả về bản ghi hợp lệ được đưa vào `resolved_order_ids`; candidate không tồn tại được ghi nhận vào `rejected_candidates`.
  - Nếu đúng 1 order hợp lệ: `status = "resolved"`, `confidence = 1.0`.
  - Nếu > 1 order hợp lệ: `status = "ambiguous"`, `confidence = 0.6`.
  - Nếu không có order nào: `status = "not_found"`, `confidence = 0.0`.
- **A2A Protocol & Handoff**:
  - Dữ liệu trao đổi thông qua cấu trúc dùng chung `CaseState`, truyền theo dạng pipeline đơn hướng (DAG), loại bỏ hoàn toàn khả năng lặp vô hạn (no circular handoffs).
  - Mọi bước bàn giao phát sinh trace event `handoff` với `actor`, `target`, và `attributes={"task": ...}`.
  - Mỗi case được cô lập hoàn toàn (`case_id` scope isolation); timeout cho mỗi request MCP gateway cấu hình 30s.

---

## 4. Evidence và conflict lifecycle

- **Validation**: Mọi phản hồi từ MCP Tool được xác thực tự động với schema `mcp-evidence-response-v1.schema.json` trước khi tiêu thụ.
- **Provenance & Scope**:
  - `evidence_ref` được thu thập từ MCP envelope và lưu trữ vào danh sách `evidence_refs` của case.
  - Tuyệt đối không giả mạo hay tái sử dụng `evidence_ref` từ case khác (tránh vi phạm hard gate `cross_scope_evidence_ref`).
- **Trace Consumption**:
  - Khi một Agent nhận dữ liệu từ MCP Tool, hệ thống tự động ghi nhận event `tool_result_consumed` với `actor`, `tool_name`, và `evidence_refs`.
- **Conflict Resolution**:
  - Trong trường hợp dữ liệu giữa các bên (ví dụ khách khiếu nại chưa nhận hàng nhưng logistics báo đã phát thành công), trạng thái được ghi nhận vào `data_conflicts` với `selected_source` ưu tiên nguồn thẩm quyền từ MCP.

---

## 5. Failure and efficiency policy

| Failure | Retry budget | Fallback | Trace event/code |
| --- | ---: | --- | --- |
| MCP timeout / mạng | 3 lần (exponential backoff 0.2s, 0.4s) | Bỏ qua tool, đánh dấu `insufficient_evidence` | `tool_result_consumed` không phát, log cảnh báo |
| Entity not found | 0 retry sau khi probe | Đặt `entity_status="not_found"`, đề xuất yêu cầu khách hàng bổ sung | `task_assigned` |
| Ambiguous Candidates | 0 retry | Đặt `entity_status="ambiguous"`, chuyển verifier đánh giá an toàn | `task_assigned` |
| Invalid Tool Result | 1 retry | Nếu lỗi format, từ chối đưa vào evidence_refs | - |

- **Query Budget & Caching Strategy**:
  - Mỗi case duy trì một local cache `mcp_cache` theo khóa `(tool_name, arguments)`.
  - Các lệnh gọi trùng tham số trong cùng một case sẽ lấy kết quả từ cache, tiết kiệm tối đa quota gọi MCP nhằm đạt điểm tối đa ở tiêu chí `efficiency` (5%).
  - Cache được xóa hoàn toàn khi chuyển sang case mới.

---

## 6. Verification invariants

Trước khi hoàn tất case và xuất file JSON, `VerifierAgent` thực thi các kiểm tra bất biến sau:
1. **Schema Integrity**: Cấu trúc tuân thủ 100% `l3b-output-v2.schema.json` (`schema_version = "day09-l3b-output-v2"`, không chứa extra fields).
2. **Financial Consistency**:
   - `financial_resolution.recommended_refund_brl` phải bằng đúng tổng của các `amount_brl` trong `refund_lines`.
   - Nếu `case_status == "no_action"`, `recommended_refund_brl` bắt buộc bằng 0.0 và `refund_lines` rỗng.
   - Số tiền hoàn không bao giờ vượt quá `refundable_total_brl`.
3. **Seller Alignment**: Mọi `late_seller_ids` trong `shipment_analysis` phải có trong danh sách seller của đơn hàng. Nếu bên chịu trách nhiệm là `seller`, `party_id` phải gán đúng ID seller liên quan.
4. **Evidence Ownership**: Toàn bộ chuỗi trong `evidence_refs` phải đúng định dạng `^ev_[A-Za-z0-9_-]{20,96}$`.
5. **Confidence Bounds**: Giá trị `confidence` luôn được chuẩn hóa trong đoạn `[0.0, 1.0]`.

---

## 7. Reproducibility

- **Python Version**: `>= 3.11` (Tested on 3.11.9 Windows 64-bit).
- **Core Dependencies**: `httpx2`, `jsonschema`, `mcp`, `python-dotenv`, `pytest`, `ruff`.
- **Determinism**: Workflow vận hành theo quy tắc xác định (deterministic state transitions), không sinh kết quả ngẫu nhiên, không phụ thuộc vào LLM temperature hay non-deterministic external calls.
- **Thực thi quy chuẩn**:
  - Chạy toàn bộ case: `day09 run`
  - Thẩm định kết quả: `day09 validate`
  - Đóng gói submission: `day09 package --output dist/submission.zip`
