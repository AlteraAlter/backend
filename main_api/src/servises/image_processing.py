import asyncio
import aiohttp
import aiofiles
import uuid
import os
import io
import time
import random
from urllib.parse import urlparse
from PIL import Image

# --- CONFIG ---
MIN_WIDTH = 2098
MIN_HEIGHT = 2098
MAX_FILE_SIZE = 9 * 1024 * 1024  # 9 MB
MAX_RETRIES = 3
TIMEOUT = 60

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif", "svg"}


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


# shared semaphore for HTTP downloads
http_semaphore = asyncio.Semaphore(_env_int("PIC_HTTP_CONCURRENCY", 10))


def clean_filename(filename: str) -> str:
    name, ext = os.path.splitext(filename)
    name = name.replace(" ", "-")
    name = "".join(c for c in name if c.isalnum() or c in "-_")
    if not name:
        name = "image"
    return f"{name}{ext.lower()}"


# =========================
# CPU-BOUND IMAGE LOGIC
# =========================
def _process_image_sync(content: bytes, clean_name: str, ext: str) -> bytes:
    """
    PIL image processing.
    MUST run in thread pool.
    Returns processed image bytes.
    """
    # SVG → return as-is
    if ext == "svg":
        return content

    image = Image.open(io.BytesIO(content))

    # RGBA → RGB
    if image.mode in ("RGBA", "LA"):
        bg = Image.new("RGB", image.size, (255, 255, 255))
        bg.paste(image, mask=image.split()[-1])
        image = bg
        ext = "jpg"

    width, height = image.size

    # Ensure minimum resolution
    if width < MIN_WIDTH or height < MIN_HEIGHT:
        scale = max(MIN_WIDTH / width, MIN_HEIGHT / height)
        image = image.resize(
            (int(width * scale), int(height * scale)),
            Image.LANCZOS,
        )

    fmt = {
        "jpg": "JPEG",
        "jpeg": "JPEG",
        "png": "PNG",
        "webp": "WEBP",
        "gif": "GIF",
    }.get(ext, "JPEG")

    quality = 95
    data = b""

    for _ in range(6):
        buffer = io.BytesIO()
        image.save(buffer, format=fmt, quality=quality)
        data = buffer.getvalue()
        if len(data) <= MAX_FILE_SIZE:
            break
        quality = int(quality * 0.85)

    if len(data) > MAX_FILE_SIZE:
        raise Exception("Image too large after compression")

    return data


# =========================
# ASYNC PIPELINE
# =========================
async def download_and_process_image(
    session: aiohttp.ClientSession,
    url: str,
    output_dir: str,
) -> str | None:
    """
    Downloads image, processes it in thread pool, saves locally.
    Returns local file path.
    """

    async with http_semaphore:
        parsed = urlparse(url)
        original_name = os.path.basename(parsed.path)
        clean_name = clean_filename(original_name)

        ext = os.path.splitext(clean_name)[1].lower().lstrip(".")
        if ext == "jpeg":
            ext = "jpg"
        if ext not in ALLOWED_EXTENSIONS:
            ext = "jpg"

        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "image/webp,image/*,*/*;q=0.8",
        }

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                async with session.get(
                    url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=TIMEOUT),
                    ssl=False,
                ) as resp:
                    if resp.status != 200:
                        raise Exception(f"HTTP {resp.status}")
                    content = await resp.read()

                # 🔥 MOVE PIL TO THREAD
                loop = asyncio.get_running_loop()
                try:
                    processed_bytes = await loop.run_in_executor(
                        None,
                        _process_image_sync,
                        content,
                        clean_name,
                        ext,
                    )
                except Exception:
                    return None

                filename = f"{uuid.uuid4().hex}_{clean_name}"
                path = os.path.join(output_dir, filename)

                async with aiofiles.open(path, "wb") as f:
                    await f.write(processed_bytes)

                return path

            except Exception:
                if attempt == MAX_RETRIES:
                    return None
                await asyncio.sleep((2**attempt) + random.uniform(0.5, 2))
