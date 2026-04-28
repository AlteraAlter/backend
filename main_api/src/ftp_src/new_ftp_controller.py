import asyncio
import aiohttp
import aiofiles
import tempfile
import os
import io
from PIL import Image
from urllib.parse import urlparse
import aioftp
import random
import time
from src.logger import log
from collections import defaultdict
from rest_framework import status
from config import FTP_HOST, FTP_PASSWORD, FTP_USERNAME

IMG_DIR = os.path.join(tempfile.gettempdir(), "kaufland_img")
os.makedirs(IMG_DIR, exist_ok=True)

FTP_REMOTE_DIR = "/automatonsoft.de/kaufland/"

MIN_WIDTH = 2098
MIN_HEIGHT = 2098
MAX_FILE_SIZE = 9 * 1024 * 1024  # 9 MB
MAX_RETRIES = 3
TIMEOUT = 60

http_semaphore = asyncio.Semaphore(3)  # Для HTTP скачивания
ftp_semaphore = asyncio.Semaphore(2)  # Для FTP загрузки

ALLOWED_EXTENSIONS = {"jpg", "png", "gif", "svg", "webp"}


class RateLimiter:
    def __init__(self, max_requests_per_minute=20):
        self.max_requests = max_requests_per_minute
        self.requests = defaultdict(list)

    async def wait_if_needed(self, host):
        now = time.time()
        host_requests = self.requests[host]
        host_requests[:] = [t for t in host_requests if now - t < 30]
        if len(host_requests) >= self.max_requests:
            wait_time = 30 - (now - host_requests[0])
            if wait_time > 0:
                log(f"Rate limit for {host}, wait {wait_time:.1f}s")
                await asyncio.sleep(wait_time)
        host_requests.append(now)


rate_limiter = RateLimiter()


def clean_filename(filename) -> str:
    """Аналог slugify, адаптированный из main.js"""
    name, ext = os.path.splitext(filename)
    name = name.replace(" ", "-")
    name = "".join(c for c in name if c.isalnum() or c in "-_")

    cyrillic_to_latin = {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ё": "yo",
        "ж": "zh",
        "з": "z",
        "и": "i",
        "й": "y",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "kh",
        "ц": "ts",
        "ч": "ch",
        "ш": "sh",
        "щ": "sch",
        "ъ": "",
        "ы": "y",
        "ь": "",
        "э": "e",
        "ю": "yu",
        "я": "ya",
        "А": "A",
        "Б": "B",
        "В": "V",
        "Г": "G",
        "Д": "D",
        "Е": "E",
        "Ё": "Yo",
        "Ж": "Zh",
        "З": "Z",
        "И": "I",
        "Й": "Y",
        "К": "K",
        "Л": "L",
        "М": "M",
        "Н": "N",
        "О": "O",
        "П": "P",
        "Р": "R",
        "С": "S",
        "Т": "T",
        "У": "U",
        "Ф": "F",
        "Х": "Kh",
        "Ц": "Ts",
        "Ч": "Ch",
        "Ш": "Sh",
        "Щ": "Sch",
        "Ъ": "",
        "Ы": "Y",
        "Ь": "",
        "Э": "E",
        "Ю": "Yu",
        "Я": "Ya",
    }
    name = "".join(cyrillic_to_latin.get(c, c) for c in name)
    name = name.replace("[^a-zA-Z0-9-_]", "")
    if not name:
        name = "image"
    return f"{name}{ext.lower()}"


async def download_and_process_image(
    session: aiohttp.ClientSession,
    url: str,
    output_dir: str,
) -> str | None:
    """
    Downloads image, validates, resizes, compresses and stores it as a TEMP file.
    Returns local file path or None on failure.
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

                # SVG → save as-is
                if ext == "svg":
                    filename = f"{int(time.time())}_{clean_name}"
                    path = os.path.join(output_dir, filename)
                    async with aiofiles.open(path, "wb") as f:
                        await f.write(content)
                    return path

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

                filename = f"{int(time.time())}_{clean_name}"
                path = os.path.join(output_dir, filename)

                async with aiofiles.open(path, "wb") as f:
                    await f.write(data)

                return path

            except Exception as e:
                log(f"[IMG] {url} error ({attempt}/{MAX_RETRIES}): {e}")
                if attempt == MAX_RETRIES:
                    return None
                await asyncio.sleep((2**attempt) + random.uniform(0.5, 2))
        parsed = urlparse(url)
        host = parsed.netloc
        await rate_limiter.wait_if_needed(host)

        original_name = os.path.basename(parsed.path)
        clean_name = clean_filename(original_name)

        ext = os.path.splitext(clean_name)[1].lower().lstrip(".") or "jpg"
        if ext == "jpeg":
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

                # SVG — сохраняем как есть
                if ext == "svg":
                    path = os.path.join(IMG_DIR, f"{int(time.time())}_{clean_name}")
                    async with aiofiles.open(path, "wb") as f:
                        await f.write(content)
                    return path

                image = Image.open(io.BytesIO(content))

                # RGBA → RGB
                if image.mode in ("RGBA", "LA"):
                    bg = Image.new("RGB", image.size, (255, 255, 255))
                    bg.paste(image, mask=image.split()[-1])
                    image = bg
                    ext = "jpg"

                width, height = image.size

                # Resize только если файл слишком большой
                if width < MIN_WIDTH or height < MIN_HEIGHT:
                    scale = max(MIN_WIDTH / width, MIN_HEIGHT / height)
                    image = image.resize(
                        (int(width * scale), int(height * scale)),
                        Image.LANCZOS,
                    )

                fmt = {"jpg": "JPEG", "png": "PNG", "webp": "WEBP", "gif": "GIF"}.get(
                    ext, "JPEG"
                )
                quality = 95

                for _ in range(5):
                    buffer = io.BytesIO()
                    image.save(buffer, format=fmt, quality=quality)
                    data = buffer.getvalue()

                    if len(data) <= MAX_FILE_SIZE:
                        break

                    quality = int(quality * 0.85)

                if len(data) > MAX_FILE_SIZE:
                    raise Exception("Не удалось ужать изображение")

                filename = f"{int(time.time())}_{clean_name}"
                path = os.path.join(IMG_DIR, filename)

                async with aiofiles.open(path, "wb") as f:
                    await f.write(data)

                return path

            except Exception as e:
                log(f"[IMG] {url} error ({attempt}/{MAX_RETRIES}): {e}")
                if attempt == MAX_RETRIES:
                    return None
                await asyncio.sleep(2**attempt)
