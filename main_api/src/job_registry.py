import asyncio
import os
import time
import uuid
from contextlib import suppress

try:
    import redis.asyncio as redis
except Exception:  # pragma: no cover - optional dependency fallback
    redis = None


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


_cancelled_jobs: set[str] = set()
_running_jobs: dict[str, asyncio.Task] = {}
_lock = asyncio.Lock()
_redis_lock = asyncio.Lock()
_redis_client = None
_ean_locks: dict[str, str] = {}

_REDIS_URL = os.getenv("JOB_REDIS_URL") or os.getenv("REDIS_URL") or ""
_REDIS_HOST = os.getenv("REDIS_HOST", "redis")
_REDIS_PORT = _env_int("REDIS_PORT", 6379)
_REDIS_DB = _env_int("REDIS_DB", 0)
_REDIS_PASSWORD = os.getenv("REDIS_PASSWORD") or None
_REDIS_PREFIX = os.getenv("JOB_REDIS_PREFIX", "kaufland:jobs")
_CANCEL_TTL = _env_int("JOB_CANCEL_TTL_SECONDS", 60 * 60 * 24)
_RUNNING_TTL = _env_int("JOB_RUNNING_TTL_SECONDS", 60 * 60 * 24)
_EAN_LOCK_TTL = _env_int("EAN_LOCK_TTL_SECONDS", 60 * 60)
_EAN_LOCK_WAIT_MS = _env_int("EAN_LOCK_WAIT_MS", 1500)
_EAN_LOCK_RETRY_MS = _env_int("EAN_LOCK_RETRY_MS", 120)


def _cancel_key(job_id: str) -> str:
    return f"{_REDIS_PREFIX}:cancel:{job_id}"


def _running_key(job_id: str) -> str:
    return f"{_REDIS_PREFIX}:running:{job_id}"


def _ean_lock_key(ean: str) -> str:
    return f"{_REDIS_PREFIX}:ean_lock:{ean}"


async def _get_redis():
    if redis is None:
        return None
    global _redis_client
    if _redis_client is None:
        async with _redis_lock:
            if _redis_client is None:
                if _REDIS_URL:
                    _redis_client = redis.from_url(_REDIS_URL, decode_responses=True)
                else:
                    _redis_client = redis.Redis(
                        host=_REDIS_HOST,
                        port=_REDIS_PORT,
                        db=_REDIS_DB,
                        password=_REDIS_PASSWORD,
                        decode_responses=True,
                    )
    return _redis_client


async def _set_cancel_flag(job_id: str) -> None:
    client = await _get_redis()
    if client is None:
        return
    with suppress(Exception):
        await client.set(_cancel_key(job_id), "1", ex=_CANCEL_TTL)


async def _clear_cancel_flag(job_id: str) -> None:
    client = await _get_redis()
    if client is None:
        return
    with suppress(Exception):
        await client.delete(_cancel_key(job_id))


async def _set_running_flag(job_id: str) -> None:
    client = await _get_redis()
    if client is None:
        return
    with suppress(Exception):
        await client.set(_running_key(job_id), "1", ex=_RUNNING_TTL)


async def _clear_running_flag(job_id: str) -> None:
    client = await _get_redis()
    if client is None:
        return
    with suppress(Exception):
        await client.delete(_running_key(job_id))


async def cancel_job(job_id: str | None) -> bool:
    normalized = str(job_id or "").strip()
    if not normalized:
        return False
    await _set_cancel_flag(normalized)
    task_to_cancel = None
    async with _lock:
        _cancelled_jobs.add(normalized)
        task_to_cancel = _running_jobs.pop(normalized, None)
    if task_to_cancel and not task_to_cancel.done():
        task_to_cancel.cancel()
    return True


async def clear_cancel(job_id: str | None) -> None:
    normalized = str(job_id or "").strip()
    if not normalized:
        return
    async with _lock:
        _cancelled_jobs.discard(normalized)
    await _clear_cancel_flag(normalized)


async def is_cancelled(job_id: str | None) -> bool:
    normalized = str(job_id or "").strip()
    if not normalized:
        return False
    async with _lock:
        if normalized in _cancelled_jobs:
            return True
    client = await _get_redis()
    if client is None:
        return False
    try:
        exists = await client.exists(_cancel_key(normalized))
    except Exception:
        return False
    if exists:
        async with _lock:
            _cancelled_jobs.add(normalized)
        return True
    return False


async def register_running_job(
    job_id: str | None, task: asyncio.Task | None = None
) -> None:
    normalized = str(job_id or "").strip()
    if not normalized:
        return
    current = task or asyncio.current_task()
    if current is None:
        return
    async with _lock:
        _running_jobs[normalized] = current
    await _set_running_flag(normalized)


async def unregister_running_job(
    job_id: str | None, task: asyncio.Task | None = None
) -> None:
    normalized = str(job_id or "").strip()
    if not normalized:
        return
    current = task or asyncio.current_task()
    async with _lock:
        existing = _running_jobs.get(normalized)
        if existing is not None and (current is None or existing is current):
            _running_jobs.pop(normalized, None)
    await _clear_running_flag(normalized)


async def acquire_ean_lock(ean: str | None, owner: str | None = None) -> str | None:
    normalized_ean = str(ean or "").strip()
    if not normalized_ean:
        return None

    token = str(owner or uuid.uuid4())
    deadline = time.monotonic() + max(0, _EAN_LOCK_WAIT_MS) / 1000
    retry_sleep = max(0.01, _EAN_LOCK_RETRY_MS / 1000)
    lock_key = _ean_lock_key(normalized_ean)

    while True:
        client = await _get_redis()
        if client is not None:
            try:
                acquired = await client.set(lock_key, token, nx=True, ex=_EAN_LOCK_TTL)
            except Exception:
                acquired = False
            if acquired:
                return token
        else:
            async with _lock:
                current_owner = _ean_locks.get(normalized_ean)
                if current_owner is None:
                    _ean_locks[normalized_ean] = token
                    return token

        if time.monotonic() >= deadline:
            return None
        await asyncio.sleep(retry_sleep)


async def release_ean_lock(ean: str | None, token: str | None) -> None:
    normalized_ean = str(ean or "").strip()
    lock_token = str(token or "").strip()
    if not normalized_ean or not lock_token:
        return

    client = await _get_redis()
    if client is not None:
        with suppress(Exception):
            current = await client.get(_ean_lock_key(normalized_ean))
            if current == lock_token:
                await client.delete(_ean_lock_key(normalized_ean))
        return

    async with _lock:
        current_owner = _ean_locks.get(normalized_ean)
        if current_owner == lock_token:
            _ean_locks.pop(normalized_ean, None)
