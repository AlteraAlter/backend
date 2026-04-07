import os
import shutil
import asyncio
import aiohttp
import tempfile
from ast import List
from main_api.src.logger import log
from .storage.sftp import SftpImageStorage
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


# =========================
# MAIN PIPELINE
# =========================
async def process_pics(pics: list[str]) -> list[str]:
    """
    Optimized image pipeline:
    - downloads images concurrently
    - uploads immediately after download
    - cleans temp files early
    """

    if not pics:
        return []

    storage = SftpImageStorage()
    timeout = aiohttp.ClientTimeout(total=120)

    download_sem = asyncio.Semaphore(MAX_PARALLEL_DOWNLOADS)
    upload_sem = asyncio.Semaphore(MAX_PARALLEL_UPLOADS)

    uploaded_urls: List[str] = []

    async with aiohttp.ClientSession(timeout=timeout) as session:

        async def download_worker(url: str) -> str | None:
            async with download_sem:
                return await download_and_process_image(session, url, TEMP_IMG_DIR)

        async def upload_worker(local_path: str) -> None:
            async with upload_sem:
                try:
                    remote_url = await storage.upload(local_path)
                    if isinstance(remote_url, str):
                        uploaded_urls.append(remote_url)
                except Exception as e:
                    log(
                        f"FTP upload failed local_path={local_path} error={e}",
                        save=True,
                    )
                finally:
                    # Cleanup immidietly
                    try:
                        os.remove(local_path)
                    except Exception as e:
                        log(
                            f"Cleanup failed local_path={local_path} error={e}",
                            save=True,
                        )

        download_tasks = [asyncio.create_task(download_worker(url)) for url in pics]
        upload_tasks = []

        for finished in asyncio.as_completed(download_tasks):
            try:
                local_path = await finished
            except Exception as e:
                log(f"Download task failed: {e}", save=True)
                continue
            log(f"DEBUG: local_path = {local_path}")
            if local_path and os.path.exists(local_path):
                upload_tasks.append(asyncio.create_task(upload_worker(local_path)))

        if not upload_tasks:
            log("No valid images downloaded", save=True)
            return []

        # 3 Wait for all uploads
        await asyncio.gather(*upload_tasks)

    return uploaded_urls
