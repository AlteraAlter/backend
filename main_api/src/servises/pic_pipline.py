from ast import List
import os
import asyncio
import aiohttp
import tempfile
from main_api.src.logger import log
from .image_processing import download_and_process_image
from .storage.ftp import FtpImageStorage


TEMP_IMG_DIR = os.path.join(tempfile.gettempdir(), "kaufland_imgs")
os.makedirs(TEMP_IMG_DIR, exist_ok=True)

# How many parallel workers run simultaniously
MAX_PARALLEL_DOWNLOADS = 5
MAX_PARALLEL_UPLOADS = 3


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

    storage = FtpImageStorage()
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
                    log(f"❌ FTP upload failed {local_path}: {e}")
                finally:
                    # Cleanup immidietly
                    try:
                        os.remove(local_path)
                    except Exception as e:
                        log(f"⚠️ Cleanup failed {local_path}: {e}")

        download_tasks = [asyncio.create_task(download_worker(url)) for url in pics]
        upload_tasks = []

        for finished in asyncio.as_completed(download_tasks):
            local_path = await finished
            if local_path and os.path.exists(local_path):
                upload_tasks.append(asyncio.create_task(upload_worker(local_path)))

        if not upload_tasks:
            log("⚠️ No valid images downloaded")
            return []

        # 3 Wait for all uploads
        await asyncio.gather(*upload_tasks)

    log(f"✅ Images processed: {len(uploaded_urls)}")
    return uploaded_urls
