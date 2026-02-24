import asyncio


_cancelled_jobs: set[str] = set()
_running_jobs: dict[str, asyncio.Task] = {}
_lock = asyncio.Lock()


async def cancel_job(job_id: str | None) -> bool:
    normalized = str(job_id or "").strip()
    if not normalized:
        return False
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


async def is_cancelled(job_id: str | None) -> bool:
    normalized = str(job_id or "").strip()
    if not normalized:
        return False
    async with _lock:
        return normalized in _cancelled_jobs


async def register_running_job(job_id: str | None, task: asyncio.Task | None = None) -> None:
    normalized = str(job_id or "").strip()
    if not normalized:
        return
    current = task or asyncio.current_task()
    if current is None:
        return
    async with _lock:
        _running_jobs[normalized] = current


async def unregister_running_job(job_id: str | None, task: asyncio.Task | None = None) -> None:
    normalized = str(job_id or "").strip()
    if not normalized:
        return
    current = task or asyncio.current_task()
    async with _lock:
        existing = _running_jobs.get(normalized)
        if existing is not None and (current is None or existing is current):
            _running_jobs.pop(normalized, None)
