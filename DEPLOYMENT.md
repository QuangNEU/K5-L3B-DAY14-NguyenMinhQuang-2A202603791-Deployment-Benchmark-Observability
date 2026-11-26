# Deployment Information

## Public URL
https://k5-l3b-day14-nguyenminhquang-2a202603791.onrender.com

## Platform
Render (Docker Web Service + Render Key Value / Redis)

## Test Commands

### Health & Readiness Check
```bash
curl -sS -o /dev/null -w '%{http_code}\n' "https://k5-l3b-day14-nguyenminhquang-2a202603791.onrender.com/health"
# Expected: 200

curl -sS -o /dev/null -w '%{http_code}\n' "https://k5-l3b-day14-nguyenminhquang-2a202603791.onrender.com/ready"
# Expected: 200
```

### API Test (with authentication)
```bash
# Không có API key → 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "https://k5-l3b-day14-nguyenminhquang-2a202603791.onrender.com/ask" \
  -H "Content-Type: application/json" \
  -d '{"question": "Hello"}'
# Expected: 401

# Có X-API-Key hợp lệ → 200
curl -X POST "https://k5-l3b-day14-nguyenminhquang-2a202603791.onrender.com/ask" \
  -H "X-API-Key: <YOUR_AGENT_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"question": "Hello"}'
# Expected: 200
```

## Environment Variables Set (on Render Dashboard)
- `AGENT_API_KEY` (secret, đặt trên Render Dashboard)
- `REDIS_URL` (Internal Key Value URL từ Render Key Value)
- `ENVIRONMENT=production`
- `RATE_LIMIT_PER_MINUTE=10`
- `DAILY_BUDGET_USD=1.0`
- `PORT` (do Render tự động inject vào container)

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
