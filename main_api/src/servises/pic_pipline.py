import os
import asyncio
import aiohttp
import tempfile
import time
from typing import List
from main_api.src.logger import log
from .storage.local_storage import LocalImageStorage
from .image_processing import download_and_process_image


TEMP_IMG_DIR = os.path.join(tempfile.gettempdir(), "kaufland_imgs")
os.makedirs(TEMP_IMG_DIR, exist_ok=True)


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


# How many parallel workers run simultaniously
MAX_PARALLEL_DOWNLOADS = _env_int("PIC_MAX_PARALLEL_DOWNLOADS", 8)
MAX_PARALLEL_UPLOADS = _env_int("PIC_MAX_PARALLEL_UPLOADS", 4)
LOCAL_IMAGE_TTL_MINUTES = _env_int("LOCAL_IMAGE_TTL_MINUTES", 30)
LOCAL_IMAGE_DIR = os.getenv("LOCAL_IMAGE_DIR", "/app/media/upload-images")
LOCAL_IMAGE_URL_PREFIX = os.getenv("LOCAL_IMAGE_URL_PREFIX", "/upload-images")
LOCAL_IMAGE_PUBLIC_BASE_URL = os.getenv("LOCAL_IMAGE_PUBLIC_BASE_URL")


def cleanup_expired_local_images(base_dir: str, ttl_minutes: int) -> None:
    os.makedirs(base_dir, exist_ok=True)
    ttl_seconds = max(60, ttl_minutes * 60)
    cutoff = time.time() - ttl_seconds

    for entry in os.scandir(base_dir):
        if not entry.is_file(follow_symlinks=False):
            continue
        try:
            if entry.stat().st_mtime < cutoff:
                os.remove(entry.path)
        except Exception as e:
            log(f"Local image cleanup failed path={entry.path} error={e}")


# =========================
# MAIN PIPELINE
# =========================
async def process_pics(pics: list[str]) -> list[str]:
    """
    Local image pipeline:
    - downloads images concurrently
    - stores in project folder
    - removes files older than TTL
    """

    if not pics:
        log("process_pics skipped: empty source list", save=True, level="warning")
        return []

    log(
        f"process_pics started input_count={len(pics)} max_parallel_downloads={MAX_PARALLEL_DOWNLOADS} max_parallel_uploads={MAX_PARALLEL_UPLOADS}",
        save=True,
        level="info",
    )
    storage = LocalImageStorage(
        base_dir=LOCAL_IMAGE_DIR,
        url_prefix=LOCAL_IMAGE_URL_PREFIX,
        public_base_url=LOCAL_IMAGE_PUBLIC_BASE_URL,
    )
    log(
        f"process_pics storage config base_dir={storage.base_dir} url_prefix={storage.url_prefix} public_base_url={storage.public_base_url}",
        save=True,
        level="info",
    )
    cleanup_expired_local_images(storage.base_dir, LOCAL_IMAGE_TTL_MINUTES)
    timeout = aiohttp.ClientTimeout(total=120)

    download_sem = asyncio.Semaphore(MAX_PARALLEL_DOWNLOADS)
    upload_sem = asyncio.Semaphore(MAX_PARALLEL_UPLOADS)

    uploaded_urls: List[str] = []

    async with aiohttp.ClientSession(timeout=timeout) as session:

        async def download_worker(url: str) -> str | None:
            async with download_sem:
                local_path = await download_and_process_image(session, url, TEMP_IMG_DIR)
                if local_path:
                    log(
                        f"process_pics download ok source_url={url} local_path={local_path}",
                        save=True,
                        level="info",
                    )
                else:
                    log(
                        f"process_pics download failed source_url={url}",
                        save=True,
                        level="warning",
                    )
                return local_path

        async def upload_worker(local_path: str) -> None:
            async with upload_sem:
                try:
                    remote_url = storage.upload(local_path)
                    if isinstance(remote_url, str):
                        uploaded_urls.append(remote_url)
                        log(
                            f"process_pics upload ok local_path={local_path} remote_url={remote_url}",
                            save=True,
                            level="info",
                        )
                except Exception as e:
                    log(
                        f"Local image publish failed local_path={local_path} error={e}",
                        save=True,
                        level="error",
                    )

        download_tasks = [asyncio.create_task(download_worker(url)) for url in pics]
        upload_tasks = []

        for finished in asyncio.as_completed(download_tasks):
            try:
                local_path = await finished
            except Exception as e:
                log(
                    f"process_pics download worker raised error={e}",
                    save=True,
                    level="error",
                )
                continue
            if local_path and os.path.exists(local_path):
                upload_tasks.append(asyncio.create_task(upload_worker(local_path)))
            else:
                log(
                    f"process_pics skipping upload local_path_invalid={local_path}",
                    save=True,
                    level="warning",
                )

        if not upload_tasks:
            log("process_pics completed with zero upload tasks", save=True, level="warning")
            return []

        # 3 Wait for all uploads
        await asyncio.gather(*upload_tasks)
    log(
        f"process_pics completed input_count={len(pics)} uploaded_count={len(uploaded_urls)}",
        save=True,
        level="info",
    )

    return uploaded_urls
