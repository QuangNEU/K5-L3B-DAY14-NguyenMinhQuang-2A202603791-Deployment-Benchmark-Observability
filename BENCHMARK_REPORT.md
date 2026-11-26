# Benchmark & Observability Report — Day 14

> Mọi con số dưới đây được lấy trực tiếp từ các file report JSON trong `reports/` (đo thực tế trên máy).

**Họ tên:** Nguyễn Minh Quang (MSSV: 2A202603791)
**Ngày chạy:** 2026-11-26
**Môi trường:** Windows 11, Python 3.14 (`.venv`), Docker Desktop

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | `< 500 ms` | Với mock LLM latency cơ bản ~120–180ms + jitter, 95% request thông thường hoàn thành dưới 500ms để đảm bảo phản hồi nhanh cho người dùng. |
| Error rate `/ask` | `< 2.0 %` | `MOCK_ERROR_RATE` mặc định là `0.01` (1%), đặt ngưỡng error budget 2% để phát hiện kịp thời khi lỗi upstream tăng bất thường mà tránh báo động giả. |
| Accuracy trên golden dataset | `≥ 80 %` (và `0` regression) | Đảm bảo agent v2 (RAG) đạt chất lượng cao trước khi deploy và không làm hỏng câu nào đã đúng ở bản trước. |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2)

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---:|---:|---:|---:|---:|---|
| 1 | 3.89 | 208.9 | 243.2 | 1720.3 | 0.67% | PASS |
| 10 | 31.35 | 207.3 | 787.0 | 1733.0 | 1.33% | FAIL (p95 > 500ms) |
| 50 | 109.60 | 211.2 | 507.1 | 1695.7 | 1.33% | FAIL (p95 > 500ms) |
| 100 | 76.66 | 548.4 | 2643.4 | 2845.9 | 0.67% | FAIL (p95 > 500ms) |

**Nhận xét:** RPS có tăng tuyến tính theo concurrency không? Vì sao?

- **Không tăng tuyến tính mãi:** Từ concurrency `1 → 10 → 50`, RPS tăng mạnh (`3.89 → 31.35 → 109.60 req/s`) nhờ xử lý bất đồng bộ (`async/await`). Nhưng khi tăng lên `100`, RPS **giảm xuống còn `76.66 req/s`** và `p50`/`p95` tăng vọt (`548.4 ms` / `2643.4 ms`) vì **1 process Uvicorn đơn lẻ bị bão hòa**, request phải xếp hàng chờ xử lý.

### 2.2 Tail latency (`--requests 300 --concurrency 20`)

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---:|---:|---:|
| 0 | 216.6 | 466.1 | 489.9 |
| 0.03 (mặc định) | 246.5 | 459.7 | 1721.7 |
| 0.1 | 391.9 | 1717.4 | 1733.7 |

**Nhận xét:** Chỉ số nào nhạy nhất với request chậm? Vì sao SLO không nên đặt theo average?

- **Chỉ số nhạy nhất:** `p99` (nhảy vọt từ `489.9 ms` lên `1721.7 ms` ngay khi mới có 3% request chậm, trong khi `avg` chỉ tăng từ `216.6 ms` lên `246.5 ms`). Khi tỷ lệ chậm lên 10% (`0.1`), cả `p95` cũng vọt lên `1717.4 ms`.
- **Vì sao không đặt SLO theo average:** Giá trị trung bình bị làm mượt bởi đa số request nhanh (ở `0.03`, `avg = 246.5 ms` trông vẫn rất ổn), nên nó **che giấu trải nghiệm tệ hại của nhóm người dùng gặp tail latency** (~1.7 giây). Đặt SLO theo `p95`/`p99` mới phản ánh đúng độ trễ thực tế mà người dùng gặp phải.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---:|---:|---:|
| Accuracy | 4.3% (1/23) | 91.3% (21/23) | 100.0% (23/23) |
| Avg tokens / câu | 58.5 | 108.8 | 112.2 |
| Tổng cost (USD) | $0.000423 | $0.000758 | $0.000778 |
| Cost / câu đúng (USD) | $0.00042315 | $0.00003607 | $0.00003381 |
| Quality gate | FAIL | PASS | PASS |

**Những câu v2 trả lời sai ban đầu và cách bạn sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| `security-02` | `token`, `hết hạn`, `chữ ký` | Thêm entry vào `KNOWLEDGE_BASE` trong `develop/utils/mock_llm.py` (và đồng bộ sang `production/utils/mock_llm.py`) với từ khóa `["jwt", "xác thực"]` giải thích JWT là token tự chứa có chữ ký số và thời gian hết hạn. |
| `scaling-03` | `cpu`, `memory`, `custom metrics` | Thêm entry vào `KNOWLEDGE_BASE` với từ khóa `["hpa", "kubernetes"]` giải thích Kubernetes HPA scale dựa trên CPU, memory hoặc custom metrics. |

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**

- **v1** tốn ít token (`58.5` tokens/câu) và không mất thời gian retrieval, nhưng chỉ đúng `1/23` câu (`4.3%`), khiến chi phí trên mỗi câu trả lời đúng (`$0.00042315`) **đắt gấp ~12.5 lần** so với v2 sau khi sửa (`$0.00003381`).
- **v2** (RAG) tốn gần gấp đôi token mỗi câu (`108.8–112.2` tokens/câu) và thêm ~20ms bước retrieval, nhưng nâng accuracy lên **`91.3% → 100.0%`**.

**Cách dùng exit code của `run_eval.py` để chặn merge trong CI (Exercise 7.3):**
- `eval/run_eval.py` trả về **exit code `0`** khi đạt quality gate (`accuracy >= --min-accuracy` và `0` câu bị regression so với `--baseline`), và trả về **exit code `1`** nếu vi phạm.
- Trong GitHub Actions, thêm bước chạy `python eval/run_eval.py --url http://localhost:8002 --min-accuracy 0.8 --baseline reports/eval_v2_fixed.json` khi có Pull Request: nếu exit code `!= 0`, job fail và tự động chặn merge vào `main`.

---

## 4. Observability stack (production)

### 4.1 Screenshot

- [x] Dashboard Grafana khi đang có tải (đã chạy stack và quan sát trực tiếp: `51.0 req/s`, Error rate `0.67%`, Latency p95 `292.51 ms`, Saturation `18`, Instances up `2`, LLM cost 1h `$0.1074`)
- [ ] Một trace chậm trong Jaeger (chưa kịp lưu ảnh trước deadline)
- [ ] Một trace lỗi trong Jaeger (chưa kịp lưu ảnh trước deadline)
- [ ] Trang Alerts của Prometheus với ít nhất 1 alert đang **firing** (chưa kịp lưu ảnh trước deadline)

### 4.2 Thí nghiệm "phá hệ thống"

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | *(chưa chạy kịp trước deadline; rule `AgentHighErrorRate`, `for: 1m`)* | — | Error rate / Requests/s theo status |
| B | `MOCK_SLOW_RATE=0.3` | *(chưa chạy kịp trước deadline; rule `AgentHighLatencyP95`, `for: 2m`)* | — | Latency p50/p95/p99 |
| C | `LLM_MODEL=mock-llm-large` | *(chưa chạy kịp trước deadline; rule `LLMCostBurnRateHigh`, `for: 2m`)* | — | LLM cost (1h) |
| D | `docker pause` 1 instance | *(chưa chạy kịp trước deadline; rule `AgentInstanceDown`, `for: 30s`)* | — | Instances up |
| E | `AGENT_VERSION=v1` | Không có alert nào firing | — | Golden dataset eval / online quality |

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

- Khi đổi `AGENT_VERSION=v1` (bỏ bước retrieval), hệ thống vẫn trả HTTP `200 OK`, latency thậm chí nhanh hơn và chi phí thấp hơn nên **không vi phạm bất kỳ metric hạ tầng nào** (4 Golden Signals vẫn xanh).
- Để phát hiện sự cố suy giảm chất lượng ("silent quality degradation") trong production, cần kết hợp:
  1. **Quality Eval tự động trong CI/CD** (`eval/run_eval.py` trên golden dataset với `--baseline`) để chặn deploy trước khi ra production.
  2. **Online evaluation / LLM-as-a-judge** chấm mẫu ngẫu nhiên traffic thật theo thời gian thực và đẩy thành Prometheus metric (vd `agent_eval_score`).
  3. **Theo dõi tín hiệu người dùng** (tỷ lệ thumbs-down, tỷ lệ hỏi lại/retry) kết hợp **A/B testing** hoặc canary release khi đổi `AGENT_VERSION`.

### 4.3 Debug bằng trace

*(Chưa kịp thu thập `trace_id` và dòng log JSON tương ứng từ Jaeger trước deadline; đã xác nhận service `observable-agent` gửi trace thành công lên Jaeger UI.)*

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---:|---:|---:|---:|---:|
| 1 | 65.78 | 190 | 220 | 1700 | 83 (1.06%) |
| 3 | *(chưa hoàn thành kịp deadline)* | | | | |

**Giải thích kết quả:**
- Ở `scale=1` (100 users, 2 phút, tổng 7,857 requests), hệ thống đạt `65.78 req/s`, `p50 = 190 ms`, `p95 = 220 ms`, `p99 = 1700 ms` (do ~3% tail latency từ `MOCK_SLOW_RATE=0.03`), tổng `83` failures (~1.06%, chủ yếu từ `MOCK_ERROR_RATE=0.01`).
- Về lý thuyết, tăng số instance từ 1 lên 3 sẽ tăng thông lượng (RPS) và giảm thời gian xếp hàng ở CPU/event loop khi tải cao, nhưng **p99 do upstream LLM chậm (1.7s/request) sẽ không giảm** vì nút thắt nằm ở thời gian phản hồi của LLM chứ không phải ở số replica của agent.

---

## 6. Kết luận

- 3 điều bạn học được về benchmark & observability:
  1. **Latency trung bình che giấu tail latency:** Chỉ cần 3% request chậm là `p99` nhảy vọt gần 1.7 giây trong khi `avg` gần như không đổi; vì vậy SLO phải đặt theo `p95`/`p99`.
  2. **Chất lượng AI phải đo song song với hiệu năng và chi phí:** `cost / câu đúng` phản ánh đúng giá trị hơn `cost / câu`, và cần chạy eval với quality gate trong CI để tránh silent regression.
  3. **3 trụ cột Observability liên kết chặt với nhau:** Metrics (Prometheus/Grafana) báo *khi nào* có vấn đề, Traces (OpenTelemetry/Jaeger) chỉ *bước nào* chậm/lỗi, và JSON Logs có `trace_id` cho biết *chi tiết chuyện gì đã xảy ra*.
- Nếu đưa agent này lên production thật, bạn sẽ thêm metric / alert nào nữa?
  - Thêm metric theo dõi **chất lượng & phản hồi người dùng** (online eval score, tỷ lệ thumbs-down), **Redis latency / connection pool** (vì rate limit & cost guard phụ thuộc Redis), **token per request histogram** (phát hiện prompt injection/prompt quá dài), và alert cho **tỷ lệ `429` / `402` tăng đột biến** (dấu hiệu bị tấn công hoặc hết ngân sách).
