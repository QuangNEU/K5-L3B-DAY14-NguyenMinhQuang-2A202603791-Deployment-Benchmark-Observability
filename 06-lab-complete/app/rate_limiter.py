"""
Rate limiting (tiêu chí 7) — Sliding window 60s lưu trên Redis.
"""
import logging
import time
import uuid

from fastapi import HTTPException
from redis.exceptions import RedisError

from app.config import settings
from app.redis_client import r

logger = logging.getLogger("agent.rate_limiter")

WINDOW_SECONDS = 60


def check_rate_limit(key: str) -> None:
    """Cho phép tối đa RATE_LIMIT_PER_MINUTE request / 60s cho mỗi API key."""
    redis_key = f"rate_limit:{key}"
    now = time.time()
    window_start = now - WINDOW_SECONDS

    try:
        pipe = r.pipeline()
        pipe.zremrangebyscore(redis_key, 0, window_start)
        pipe.zcard(redis_key)
        _, current_count = pipe.execute()

        if current_count >= settings.rate_limit_per_minute:
            oldest = r.zrange(redis_key, 0, 0, withscores=True)
            retry_after = (
                max(1, int(WINDOW_SECONDS - (now - oldest[0][1])) + 1)
                if oldest
                else WINDOW_SECONDS
            )
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={"Retry-After": str(retry_after)},
            )

        member = f"{now}:{uuid.uuid4().hex[:8]}"
        pipe = r.pipeline()
        pipe.zadd(redis_key, {member: now})
        pipe.expire(redis_key, WINDOW_SECONDS + 5)
        pipe.execute()
    except HTTPException:
        raise
    except RedisError as exc:
        logger.warning("Redis unavailable in rate_limiter: %s", exc)
