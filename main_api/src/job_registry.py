import asyncio


_cancelled_jobs: set[str] = set()
_lock = asyncio.Lock()


async def cancel_job(job_id: str | None) -> bool:
    normalized = str(job_id or "").strip()
    if not normalized:
        return False
    async with _lock:
        _cancelled_jobs.add(normalized)
    return True


async def clear_cancel(job_id: str | None) -> None:
    normalized = str(job_id or "").strip()
    if not normalized:
        return
    async with _lock:
        _cancelled_jobs.discard(normalized)


async def is_cancelled(job_id: str | None) -> bool:
    normalized = str(job_id or "").strip()
    if not normalized:
        return False
    async with _lock:
        return normalized in _cancelled_jobs
