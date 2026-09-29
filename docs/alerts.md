# Template Alert và Runbook

Mỗi alert phải dựa trên triệu chứng người dùng hoặc SLO, không dựa trực tiếp vào tên implementation nội bộ. Định nghĩa máy đọc được nằm trong [`../config/alert_rules.yaml`](../config/alert_rules.yaml); dashboard để kiểm tra nằm ở `http://127.0.0.1:8000/dashboard`.

## Alert 1

- Tên: `HighLatencyP95`
- Severity: P2 (người dùng vẫn nhận được câu trả lời nhưng chậm)
- Duration: 5m
- Kênh thông báo: Slack `#day13-llmops-alerts`
- SLI/SLO liên quan: `fast_successful_requests` — 99.5% request có `response_sent` với `latency_ms <= 3000` trong 28 ngày.
- Điều kiện và thời gian duy trì: P95 `latency_ms` của `response_sent` > 2000 ms trong cửa sổ 5 phút, kéo dài liên tục 5 phút. Đặt dưới SLO line 3000 ms vì challenge `rag_slow` (P95 2656 ms) không chạm 3000 ms — alert phải bắt được suy giảm trước khi vi phạm SLO.
- Ảnh hưởng tới người dùng: câu trả lời chậm gấp ~15 lần baseline (~150 ms); nếu tiếp tục xấu đi sẽ vượt 3000 ms và tiêu error budget của SLO chính.
- Ba bước kiểm tra đầu tiên:
  1. Mở panel **Latency percentiles and TTFT**: nếu TTFT P95 vẫn ~50 ms mà P95 tăng thì chậm nằm trước bước LLM (retrieval/prompt fetch), nếu TTFT cũng tăng thì do LLM.
  2. Lọc log chậm: `event == "response_sent" and latency_ms > 3000`, lấy `correlation_id` và `trace_id`.
  3. Mở trace trên Langfuse, xem waterfall: so sánh thời lượng span `retrieval` với `llm-generation`.
- Mitigation tạm thời: nếu `retrieval` chậm, chuyển sang fallback doc/cache hoặc giảm top-k; nếu do prompt fetch, tăng `cache_ttl_seconds`; nếu do LLM, chuyển model nhỏ hơn hoặc giới hạn `max_tokens`.
- Owner: Nguyễn Việt Hùng (on-call LLMOps)

## Alert 2

- Tên: `HighErrorRate`
- Severity: P1 (người dùng nhận lỗi 500, không có câu trả lời)
- Duration: 5m
- Kênh thông báo: Slack `#day13-llmops-alerts`
- SLI/SLO liên quan: guardrail `error_rate_pct_max = 2`; mọi request lỗi cũng là bad event của SLO chính.
- Điều kiện và thời gian duy trì: `count(request_failed) / count(request_received) * 100 > 2` trong cửa sổ 5 phút, với ít nhất 10 request để tránh báo động giả khi traffic thấp, kéo dài 5 phút.
- Ảnh hưởng tới người dùng: request trả HTTP 500; tính năng chat không dùng được với phần traffic bị lỗi.
- Ba bước kiểm tra đầu tiên:
  1. Mở panel **Error rate and retrieval success**: xem breakdown `error_type` và `tool_success_rate_pct` (retrieval có đang lỗi không).
  2. Lọc log `event == "request_failed"`, đọc `error_type`, `payload.detail`, `tool_name` và lấy `correlation_id`.
  3. Mở trace tương ứng: span nào có `level=ERROR` (ví dụ `retrieval` với `status_message=RuntimeError`).
- Mitigation tạm thời: nếu lỗi ở retrieval/vector store thì bật fallback trả lời không có context hoặc tắt tính năng RAG; nếu do deploy mới thì rollback; thông báo trạng thái trên kênh Slack.
- Owner: Nguyễn Việt Hùng (on-call LLMOps)

## Alert 3

- Tên: `CostPerRequestSpike`
- Severity: P2 (chưa ảnh hưởng chức năng nhưng đốt ngân sách)
- Duration: 15m
- Kênh thông báo: Slack `#day13-llmops-alerts`
- SLI/SLO liên quan: guardrail `daily_cost_usd_max = 2.5`; baseline chi phí trung bình ≈ $0.0021/request.
- Điều kiện và thời gian duy trì: trung bình `cost_usd` của `response_sent` > $0.0042 (2× baseline) trong cửa sổ 15 phút, kéo dài 15 phút.
- Ảnh hưởng tới người dùng: câu trả lời dài bất thường (chậm hơn, khó đọc); nếu kéo dài sẽ vượt ngân sách ngày và phải cắt dịch vụ.
- Ba bước kiểm tra đầu tiên:
  1. Mở panel **Input and output tokens** và **Cost over time**: xác định tăng do `tokens_in` (prompt/context phình) hay `tokens_out` (câu trả lời dài).
  2. Lọc log `response_sent` có `cost_usd` cao, xem `prompt_version`, `feature`, `model` để biết có trùng thời điểm đổi prompt/model không.
  3. Mở trace, xem `usage`/`cost` của span `llm-generation` và prompt version được link.
- Mitigation tạm thời: rollback label `production` về prompt version trước (`python scripts/prompt_versioning.py promote --version <n>`), đặt giới hạn `max_tokens`, hoặc chuyển feature tốn kém sang model rẻ hơn.
- Owner: Nguyễn Việt Hùng (on-call LLMOps)
