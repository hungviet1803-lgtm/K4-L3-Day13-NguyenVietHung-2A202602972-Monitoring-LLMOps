# Báo cáo cá nhân — K4-L3A Day 13 Monitoring & LLMOps

> Mỗi học viên hoàn thiện một file duy nhất này. Khi dẫn evidence, dùng đường dẫn tương đối, ví dụ `evidence/07-trace-waterfall.png`.

## 1. Thông tin học viên

- **Họ và tên:** Nguyễn Việt Hùng
- **MSSV:** 2A202602972
- **Lớp:** K4-L3A
- **Repository URL:** https://github.com/hungviet1803-lgtm/K4-L3A-Day13-NguyenVietHung-2A202602972-Monitoring-LLMOps
- **Commit SHA cuối:**
- **Challenge ID:** `day13-k4-l3a-monitoring-llmops-v1`
- **Tên project Langfuse cá nhân:** `day13-k4-l3a-2A202602972`

## 2. Evidence index

Điền đúng đường dẫn tới evidence thực tế. Có thể đổi tên hoặc dùng nhiều ảnh nếu cần.

| Evidence | Đường dẫn |
|---|---|
| Pytest cuối | `evidence/01-pytest.png` |
| Log validator | `evidence/02-log-validator.png` |
| Dashboard validator | `evidence/03-dashboard-validator.png` |
| Structured log | `evidence/04-structured-log.png` |
| PII redaction | `evidence/05-pii-redaction.png` |
| Trace list | `evidence/06-trace-list.png` |
| Trace waterfall | `evidence/07-trace-waterfall.png` |
| Trace metadata | `evidence/08-trace-metadata.png` |
| Prompt versions | `evidence/09-prompt-versions.png`, `evidence/09b-prompt-v2-production.png` (trước rollback: `production` ở v2) |
| Prompt rollback | `evidence/10-prompt-rollback.png` (sau rollback: `production` về v1; so với `09b` trước rollback) |
| Dashboard runtime | `evidence/11-dashboard-overview.png` |
| Incident metric | `evidence/12-incident-metric.png` |
| Incident log | `evidence/13-incident-log.png` |
| Incident trace | `evidence/14-incident-trace.png` |

## 3. Kết quả kỹ thuật

| Nội dung | Baseline | Kết quả cuối | Nhận xét |
|---|---|---|---|
| `validate_logs.py` | 30/100 — thiếu field bắt buộc ở 20/21 record, 0 correlation ID, thiếu enrichment | 100/100 — 0 record thiếu field, 73 correlation ID duy nhất, 0 PII leak | Thêm correlation ID middleware, bind context vào log, scrub PII trên mọi field trước khi ghi |
| `validate_dashboard.py` | Hợp lệ 6/6 panel | Hợp lệ 6/6 panel | Contract giữ nguyên; dashboard runtime dựng tại `/dashboard` đọc đúng contract |
| `pytest` | 22 passed | 29 passed | Thêm test PII, test header/enrichment/log sạch PII (CP1) và test tổng hợp dashboard (CP2) |
| Số traces hợp lệ | 0 (chỉ có root `lab-agent-run`, prompt `local-fallback`) | 36 traces có root → `retrieval` + `llm-generation` (các trace sau CP2 có thêm `prompt-fetch`) | Generation có model, prompt link, usage, cost, TTFT |
| Số PII leak | 0 (validator chỉ đếm; `message_preview` đã qua `summarize_text`) | 0 | Scrubber nay chạy trên toàn bộ event, không chỉ `payload` |
| Latency P95 / TTFT P95 | P50 483 ms, P95 2714 ms / TTFT P95 51 ms | Challenge không incident: P95 153 ms / TTFT P95 50 ms; khi `rag_slow`: P95 2656 ms / TTFT P95 50 ms | P95 baseline ban đầu bị đẩy lên bởi fetch prompt lạnh và endpoint async chặn event loop (đã sửa, xem mục 8) |
| Retrieval success rate | 100% | 100% | `rag_slow` làm retrieval chậm chứ không lỗi, nên success rate không đổi — tín hiệu nằm ở latency |

## 4. Logging và PII

- **Cách tạo/nhận và truyền correlation ID:** `CorrelationIdMiddleware` (`app/middleware.py`) gọi `clear_contextvars()` ở đầu mỗi request để không rò context giữa các request. Nếu client gửi header `x-request-id` hợp lệ (chỉ gồm chữ, số, `._-`, tối đa 64 ký tự) thì dùng lại, ngược lại sinh `req-<8 hex>` từ `uuid4`. ID được `bind_contextvars` nên mọi dòng log trong request đều có `correlation_id`; ID cũng được truyền vào `agent.run(...)` để gắn vào trace, trả về trong body (`correlation_id`) và header `x-request-id`, kèm `x-response-time-ms`.
- **Các metadata được ghi vào structured log:** `ts` (ISO, UTC), `level`, `service`, `event`, `correlation_id`, `user_id_hash` (SHA-256 cắt 12 ký tự), `session_id`, `feature`, `model`, `env`. Event `response_sent` có thêm `latency_ms`, `ttft_ms`, `tokens_in`, `tokens_out`, `cost_usd`, `quality_score`, `tool_name`, `tool_success`; event `request_failed` có `error_type`.
- **Cách bảo đảm PII được scrub trước khi ghi:** processor `scrub_event` được đăng ký sau `format_exc_info` và trước `JsonlFileProcessor`/`JSONRenderer`, nên cả file log lẫn console chỉ nhận dữ liệu đã scrub. Scrubber duyệt đệ quy mọi giá trị chuỗi (kể cả dict/list lồng nhau và chi tiết exception), không chỉ `payload`. Pattern trong `app/pii.py`: email, số điện thoại Việt Nam (`0`/`+84`, có dấu cách/chấm/gạch), CCCD 12 số, thẻ 16 số, hộ chiếu Việt Nam; pattern thẻ chạy trước CCCD/phone để tránh bị match một phần. `user_id` gốc không bao giờ được log — chỉ ghi `user_id_hash`.
- **Cách kiểm chứng kết quả:** đổi tên log baseline thành `data/logs.baseline.jsonl`, chạy lại `scripts/load_test.py` rồi `scripts/validate_logs.py` → 100/100, 10 correlation ID duy nhất, 0 PII leak (`evidence/02-log-validator.png`). Log mẫu cho thấy email/phone/thẻ trong câu hỏi đã thành `[REDACTED_EMAIL]`, `[REDACTED_PHONE_VN]`, `[REDACTED_CREDIT_CARD]` (`evidence/05-pii-redaction.png`). `pytest` có test tự động cho từng loại PII, cho header `x-request-id`/`x-response-time-ms`, việc tái sử dụng ID của client, enrichment và việc file log không chứa PII thô.

## 5. Tracing và prompt versioning

- **Cách xác nhận traces do chính tôi tạo trong project cá nhân:** key trong `.env` thuộc project `day13-k4-l3a-2A202602972`; `/health` trả `tracing_enabled: true` và `auth_check()` thành công. Mỗi trace có `userId` là hash 12 ký tự, `sessionId`, `environment=dev` và `metadata.correlation_id` trùng với `x-request-id`/log của request tôi gửi.
- **Cấu trúc root/retrieval/generation observations:** root `lab-agent-run` (type `agent`, `@observe`, không capture raw input/output) chứa 3 con: `retrieval` (type `retriever`, input `query_preview` đã scrub, output `doc_count` + preview tài liệu, `level=ERROR` khi retrieval lỗi) `prompt-fetch` (type `span`, output `prompt_version`/`prompt_source`, `level=WARNING` khi rơi về local-fallback — thêm sau khi waterfall cho thấy ~3 s chưa được giải thích giữa retrieval và generation do fetch prompt lạnh) và `llm-generation` (type `generation`, có `model`, prompt được link qua `prompt=managed_prompt`, `usage_details` input/output, `cost_details` input/output, `completion_start_time` = start + TTFT, input/output chỉ là preview đã scrub PII). Waterfall cho thấy ngay bước nào chậm.
- **Cách nối trace với log:** trong `LabAgent.run` lấy `get_current_trace_id()` và `bind_contextvars(trace_id=...)`, nên log `response_sent`/`request_failed` có cả `correlation_id` và `trace_id`; ngược lại trace có `metadata.correlation_id`. Response API trả `trace_id` và `prompt_version`.
- **Prompt name:** `day13-chat` (text prompt, giữ 3 biến `{{feature}}`, `{{docs}}`, `{{message}}`).
- **Version/label baseline:** v1 — labels `baseline`, `production`; template gốc.
- **Version/label candidate:** v2 — label `candidate`; thêm dòng `Answer in at most 3 short sentences.`
- **Trace ID của mỗi version:** cùng input *"Explain why metrics traces and logs work together"*:
  - `baseline` → v1: `7f4f5c8a168843dcec815ba9c9b587ee` (`req-29cc955e`)
  - `candidate` → v2: `12f227345363b7fdb048233d0ab4741c` (`req-e2099aab`)
  - `production` sau khi promote → v2: `92b4de03443e4cd4377efc586e4dedd8` (`req-4b9af992`)
  - `production` sau rollback → v1: `c760fb8ef8757bf72e012069617143da` (`req-07331746`)
- **Cách promote và rollback `production`:** `scripts/prompt_versioning.py` dùng `Langfuse.update_prompt(name, version, new_labels=["production"])` — label chỉ gắn cho một version nên promote v2 tự gỡ khỏi v1. Promote: `python scripts/prompt_versioning.py promote --version 2`; rollback: `... promote --version 1`; kiểm tra: `... status` và `... run --label production` (trace ghi `prompt_version`). App cache prompt 60 s nên thay đổi có hiệu lực tối đa sau 60 s, không cần deploy lại.

## 6. Dashboard, SLO và alerts

- **Dashboard và sáu panel:** route `GET /dashboard` (`app/dashboard.py`) đọc `data/logs.jsonl`, lấy tiêu đề/đơn vị/threshold từ `config/dashboard.yaml`, cửa sổ 60 phút, bucket 1 phút, tự refresh 30 s. Sáu panel: (1) Latency P50/P95/P99 + TTFT P95, ms, SLO P95 ≤ 3000; (2) Request traffic, requests/phút, ≥ 1; (3) Error rate + breakdown `error_type` + retrieval success, %, ≤ 2; (4) Cost cộng dồn + bar theo phút, USD, total ≤ 2.5; (5) Tokens in/out cộng dồn, tokens, ≤ 50,000; (6) Quality proxy mean, 0–1, ≥ 0.75. Mỗi panel có đường SLO đứt nét và badge OK/BREACH.
- **SLO và lý do chọn:** giữ `fast_successful_requests`: 99.5% request có `response_sent` với `latency_ms ≤ 3000` trong 28 ngày. Baseline khi cache prompt nóng P95 ≈ 150 ms; chỉ request fetch prompt lạnh vượt 3000 ms. SLO giữ 3000 ms làm ranh giới "người dùng thấy hỏng", còn alert latency đặt sớm hơn ở 2000 ms vì challenge `rag_slow` (P95 2656 ms) không chạm SLO line. Request lỗi không có `response_sent` nên cũng là bad event.
- **Cách tính error budget:** budget = (1 − 0.995) × tổng request trong 28 ngày = 0.5%. Ví dụ 10,000 req/ngày → 280,000 req → tối đa 1,400 request chậm/lỗi, tương đương 3.36 giờ hỏng hoàn toàn. Burn rate ≥ 14.4 trong 1 h (≈ 2% budget/giờ) là mức page; ≥ 6 trong 6 h là ticket.
- **Ba alert và runbook tương ứng:** (`config/alert_rules.yaml`, `docs/alerts.md`, kênh Slack `#day13-llmops-alerts`, owner: tôi)
  1. `HighLatencyP95` — P2 — P95 > 2000 ms trong 5 phút (hạ từ 3000 ms sau challenge, xem mục 7) → runbook `docs/alerts.md#alert-1` (so TTFT với latency, mở waterfall retrieval vs generation).
  2. `HighErrorRate` — P1 — error rate > 2% trong 5 phút, tối thiểu 10 request → `#alert-2` (breakdown `error_type`, span `level=ERROR`).
  3. `CostPerRequestSpike` — P2 — cost trung bình > $0.0042 (2× baseline) trong 15 phút → `#alert-3` (tokens in/out, `prompt_version`, rollback prompt).

## 7. Điều tra challenge

- **Challenge ID:** `day13-k4-l3a-monitoring-llmops-v1` (cohort K4, feature bị ảnh hưởng `monitoring`, ngưỡng `latency_threshold_ms` = 2000). File `config/challenge.json` giữ nguyên bản Lab Coach gửi, đã `.gitignore`, không commit.
- **Khoảng thời gian điều tra (UTC, 29/09/2026):**
  - Baseline, chưa bật incident: 09:22:17–09:22:20 — `load_test.py --challenge --concurrency 5`.
  - Incident: `inject_incident.py` bật lúc 09:23:37, chạy challenge 2 lượt đến 09:23:48.
  - Phục hồi: tắt incident lúc 09:26:09, chạy lại challenge để xác nhận.
- **Triệu chứng từ metrics:** panel **Latency percentiles and TTFT** (`evidence/12-incident-metric.png`):

  | Cửa sổ | n | P50 | P95 | TTFT P95 | > 2000 ms | Lỗi |
  |---|---|---|---|---|---|---|
  | Baseline 09:22 | 5 | 152 ms | 153 ms | 50 ms | 0 | 0 |
  | Incident 09:23 | 10 | 2653 ms | 2656 ms | 50 ms | 10/10 | 0 |
  | Sau khi tắt 09:26 | 5 | — | ~320 ms (client) | — | 0 | 0 |

  P95 tăng ~17× và vượt ngưỡng challenge 2000 ms, nhưng **TTFT P95 không đổi (50 ms)**, error rate 0% và retrieval success 100%. Vậy request vẫn thành công, phần chậm nằm **trước** khi LLM sinh token đầu tiên. Traffic, cost, tokens và quality không đổi. Trên ảnh dashboard, cụm điểm ~2650 ms ở khoảng −10 phút là incident; badge BREACH và P95 3773 ms của cả cửa sổ 60 phút còn bị kéo lên bởi các request fetch prompt lạnh trước đó (điểm ~5300 ms ở khoảng −35 phút), nên bảng trên tách riêng từng cửa sổ.
- **Log line và correlation ID liên quan:** lọc `event == "response_sent" and latency_ms > 2000` trong 09:23:37–09:23:49 được 10/10 request, đều `feature=monitoring`. Chọn `req-28184cfe` (`evidence/13-incident-log.png`):
  ```json
  {"service": "api", "latency_ms": 2652, "ttft_ms": 50, "tokens_in": 35, "tokens_out": 92, "cost_usd": 0.001485, "quality_score": 0.8, "tool_name": "retrieval", "tool_success": true, "prompt_version": "1", "event": "response_sent", "feature": "monitoring", "session_id": "k4-l3a-challenge-s03", "user_id_hash": "dc9b2ec8da9d", "trace_id": "1c26a633d8785f21960664eb9fe7a8e0", "correlation_id": "req-28184cfe", "env": "dev", "level": "info", "ts": "2026-09-29T09:23:42.283795Z"}
  ```
  Log cho `latency_ms` 2652 nhưng `ttft_ms` 50 và `tool_success: true`, đồng thời có luôn `trace_id` để mở trace.
- **Trace ID và span gây ảnh hưởng:** trace `1c26a633d8785f21960664eb9fe7a8e0` (metadata `correlation_id = req-28184cfe`, `evidence/14-incident-trace.png`):

  | Span | Type | Baseline (`c09ea2bc3aa6d81dd22a7acb254e10a4`, `req-e9853ad5`) | Incident |
  |---|---|---|---|
  | `lab-agent-run` | agent | 152 ms | 2653 ms |
  | `retrieval` | retriever | ~0 ms | **2502 ms (94%)** |
  | `prompt-fetch` | span | 0 ms | 0 ms |
  | `llm-generation` | generation | ~150 ms | 150 ms |

  Mọi span đều `level=DEFAULT` (không lỗi). Chỉ `retrieval` thay đổi.
- **Root cause:** bước retrieval (vector store / `app/mock_rag.retrieve`) bị chậm thêm ~2.5 s mỗi request, do incident `rag_slow` được bật (mô phỏng vector store quá tải hoặc truy vấn chậm). LLM, prompt và dữ liệu không phải nguyên nhân. Ba bằng chứng cùng chỉ về đây: metric cho thấy latency tăng mà TTFT đứng yên; log cho thấy request thành công nhưng chậm; trace cho thấy `retrieval` chiếm 94% thời gian.
- **Fix action:** tắt nguồn gây chậm (`python scripts/inject_incident.py --disable` lúc 09:26:09) — tương đương khôi phục/scale vector store. Kiểm chứng: chạy lại cùng 5 query challenge, latency về 195–323 ms (client side), 0 request > 2000 ms. Trước đó, trong lúc chuẩn bị, đã sửa `/chat` từ `async def` sang `def`: `agent.run()` là code đồng bộ nên từng chặn event loop, khiến 5 request đồng thời phải xếp hàng (client thấy 8–11 s dù server chỉ xử lý 167 ms). Nếu không sửa, `rag_slow` sẽ bị khuếch đại thành ~5 × 2.5 s cho người dùng cuối hàng.
- **Preventive measure:**
  1. Hạ `HighLatencyP95` từ 3000 xuống 2000 ms (`config/alert_rules.yaml`). Với ngưỡng cũ, incident này (P95 2656 ms) **không kích hoạt alert nào**. Ngưỡng mới bắt được nó sau 5 phút.
  2. Đặt timeout cho retrieval (ví dụ 800 ms) và fallback trả lời không có context, gắn `level=WARNING` trên span `retrieval`. Như vậy latency có trần, và việc suy giảm vẫn nhìn thấy được qua trace/log.
  3. Thêm SLI riêng cho retrieval (P95 duration của span `retriever`) để phân biệt retrieval chậm với LLM chậm ngay trên dashboard, không cần mở trace.

## 8. Giải thích và tự đánh giá

- **Một quyết định kỹ thuật quan trọng và lý do:** scrub PII bằng một structlog processor chạy trên **mọi** field (đệ quy), đặt trước file writer và JSON renderer, thay vì scrub từng chỗ gọi log. Như vậy log mới, chi tiết exception hay field thêm sau này đều được bảo vệ mặc định. Tương tự, trace chỉ nhận preview đã scrub (`capture_input=False` ở root, input/output của span là `summarize_text`).
- **Một lỗi/blocker đã gặp:** (1) Sau khi điền key Langfuse, `/health` vẫn trả `tracing_enabled: false`. (2) Waterfall trace có ~3 s không thuộc span nào (root 3.32 s, retrieval 0 ms, generation 152 ms). (3) Khi chạy challenge baseline, client đo 8–11 s dù server log chỉ 167 ms.
- **Cách tìm nguyên nhân và xử lý:** (1) `uvicorn --env-file` chỉ đọc `.env` lúc khởi động, `--reload` không theo dõi `.env` → khởi động lại server; xác nhận bằng `auth_check()`. (2) Khoảng trống nằm giữa retrieval và generation, đúng chỗ gọi `get_prompt` → fetch prompt lạnh từ Langfuse; thêm span `prompt-fetch` (có `level=WARNING` khi rơi về local fallback). (3) So `latency_ms` trong log với thời gian client đo → chênh lệch là thời gian xếp hàng; nguyên nhân là `async def chat` gọi `agent.run()` đồng bộ nên chặn event loop → đổi sang `def` để chạy trong threadpool, latency client về ~450 ms. Ngoài ra API `GET /api/public/traces` trả 410 cho organization mới → chuyển sang `GET /api/public/v2/observations`.
- **Cách hiểu luồng Metrics → Logs → Traces:** metric trả lời *có vấn đề không, bao nhiêu, từ lúc nào* (P95 tăng từ 153 lên 2656 ms trong khi TTFT đứng yên). Log trả lời *request nào bị ảnh hưởng*: lọc theo thời gian và ngưỡng để lấy `correlation_id`, và log có sẵn `trace_id`. Trace trả lời *chậm ở đâu trong request*: span `retrieval` 2502 ms. `correlation_id` và `trace_id` được ghi ở cả log lẫn trace metadata nên có thể đi hai chiều.
- **Vai trò của prompt version, token/cost, SLO hoặc rollback trong vận hành LLM:** prompt là "code" thay đổi ngoài deploy; label (`production`, `candidate`) và `prompt_version` trên mỗi trace/log cho phép quy một thay đổi latency/cost/quality về đúng version, rồi rollback trong vài giây bằng cách chuyển label, không cần deploy (cache 60 s). Token/cost theo từng request giúp phát hiện prompt hoặc câu trả lời phình ra (alert `CostPerRequestSpike`). SLO + error budget quyết định khi nào phải dừng thay đổi để ưu tiên ổn định.
- **Điều quan trọng nhất đã học:** ngưỡng alert phải kiểm chứng bằng incident thật. Alert latency ban đầu đặt ở SLO line 3000 ms nghe hợp lý, nhưng challenge `rag_slow` (P95 2656 ms) đi qua mà không kích hoạt gì — chỉ nhờ so với baseline thật (~150 ms) mới thấy cần đặt alert sớm hơn.
- **Hạn chế hoặc phần chưa hoàn thành, nếu có:** dashboard là trang HTML tự render (route `/dashboard`), đọc toàn bộ `data/logs.jsonl` mỗi lần refresh — đủ cho lab nhưng không phù hợp khi log lớn (cần Loki/Grafana hoặc DB). Alert mới là định nghĩa YAML + runbook, chưa có engine thật gửi Slack. Timeout/fallback cho retrieval mới dừng ở đề xuất, chưa cài đặt.

## 9. Checklist trước khi nộp

- [ ] Kết quả và evidence thuộc commit SHA cuối.
- [ ] Tất cả ảnh/output mở được bằng đường dẫn tương đối.
- [ ] Incident evidence nối đúng metric → log → trace.
- [ ] Trace/prompt evidence thuộc project Langfuse cá nhân và ảnh không lộ key/secret.
- [ ] Repository chạy lại được theo README.
- [ ] Không có secret, API key, PII thô hoặc evidence của người khác/lớp khác.
- [ ] URL repo và commit SHA cuối đã được nộp trên LMS/Codelabs.
