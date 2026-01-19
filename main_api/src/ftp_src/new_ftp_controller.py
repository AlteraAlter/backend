import asyncio
import aiohttp
import aiofiles
import os
import io
from PIL import Image
from urllib.parse import urlparse
import aioftp
import random
import time
from main_api.src.logger import log
from collections import defaultdict
from config import FTP_HOST, FTP_PASSWORD, FTP_USERNAME


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMG_DIR = os.path.join(BASE_DIR, "media", "imgs")
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
                log(f"⏳ Rate limit для {host}, ждем {wait_time:.1f}с")
                await asyncio.sleep(wait_time)
        host_requests.append(now)


rate_limiter = RateLimiter()


def clean_filename(filename):
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


async def download_and_process_image(session: aiohttp.ClientSession, url: str):
    async with http_semaphore:
        parsed = urlparse(url)
        host = parsed.netloc
        await rate_limiter.wait_if_needed(host)

        original_name = os.path.basename(parsed.path)
        clean_name = clean_filename(original_name)

        name, ext = os.path.splitext(original_name)
        ext = ext.lower().lstrip(".") or "jpg"
        if ext == "jpeg":
            ext = "jpg"

        timestamp = int(time.time())

        MAX_FILE_SIZE = 9 * 1024 * 1024
        MIN_W, MIN_H = 2098, 2098
        ALLOWED_EXT = {"jpg", "png", "webp", "gif", "svg"}

        def build_path(extension):
            return os.path.join(IMG_DIR, f"{clean_name}_{timestamp}.{extension}")

        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "image/webp,image/*,*/*;q=0.8",
        }

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                async with session.get(
                    url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=60),
                    ssl=False,
                ) as resp:
                    if resp.status == 429:
                        wait = int(resp.headers.get("Retry-After", 60))
                        await asyncio.sleep(wait + random.uniform(1, 3))
                        continue

                    if resp.status != 200:
                        raise Exception(f"HTTP {resp.status}")

                    content = await resp.read()

                # SVG — сохраняем как есть
                if ext == "svg":
                    path = build_path("svg")
                    async with aiofiles.open(path, "wb") as f:
                        await f.write(content)
                    return path

                image = Image.open(io.BytesIO(content))

                if ext not in ALLOWED_EXT:
                    ext = "jpg"

                # RGBA → RGB
                if image.mode in ("RGBA", "LA"):
                    bg = Image.new("RGB", image.size, (255, 255, 255))
                    bg.paste(image, mask=image.split()[-1])
                    image = bg
                    ext = "jpg"

                width, height = image.size

                # Resize только если файл слишком большой
                if len(content) > MAX_FILE_SIZE:
                    scale = max(MIN_W / width, MIN_H / height)
                    if scale != 1:
                        new_size = (int(width * scale), int(height * scale))
                        image = image.resize(new_size, Image.LANCZOS)

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

                path = build_path(ext)
                async with aiofiles.open(path, "wb") as f:
                    await f.write(data)

                return path

            except Exception as e:
                log(f"[{url}] ошибка ({attempt}/{MAX_RETRIES}): {e}")
                if attempt == MAX_RETRIES:
                    return None
                await asyncio.sleep((2**attempt) + random.uniform(1, 5))


async def upload_to_ftp(local_path: str):
    LOCAL_SAVE_DIR = "imgs/"

    filename = os.path.basename(local_path)
    local_copy_path = os.path.join(LOCAL_SAVE_DIR, filename)
    async with aiofiles.open(local_path, "rb") as src, aiofiles.open(
        local_copy_path, "wb"
    ) as dst:
        await dst.write(await src.read())

    log(f"Путь до файла: {local_path}")
    max_retries = 3

    for attempt in range(1, max_retries + 1):
        try:
            async with ftp_semaphore:
                async with aioftp.Client.context(
                    host=FTP_HOST, user=FTP_USERNAME, password=FTP_PASSWORD, port=21
                ) as client:
                    try:
                        await client.change_directory(FTP_REMOTE_DIR)
                        await client.upload(local_path)
                        log(f"Загрузили {filename} в {FTP_REMOTE_DIR}")
                        return f"https://automatonsoft.de/kaufland/{filename}"
                    except ConnectionResetError as e:
                        log(
                            f"⚠️ ConnectionResetError при загрузке {filename} (попытка {attempt}): {e}"
                        )
                        if attempt == max_retries:
                            raise
                        await asyncio.sleep(2**attempt * random.uniform(0.1, 1))
                    except Exception as e:
                        log(f"❌ Ошибка FTP для {filename} (попытка {attempt}): {e}")
                        if attempt == max_retries:
                            raise
                        await asyncio.sleep(2**attempt * random.uniform(0.1, 1))
        except Exception as e:
            log(f"❌ Не удалось установить FTP соединение (попытка {attempt}): {e}")
            if attempt == max_retries:
                raise
            await asyncio.sleep(5 * attempt * random.uniform(0.1, 1))
    raise Exception(f"Не удалось загрузить {filename} после {max_retries} попыток")


async def process_pics(pics: list[str]):
    connector = aiohttp.TCPConnector(
        limit=5, limit_per_host=2, ttl_dns_cache=300, use_dns_cache=True
    )
    timeout = aiohttp.ClientTimeout(total=120, connect=30)
    async with aiohttp.ClientSession(
        connector=connector,
        timeout=timeout,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        },
    ) as session:
        semaphore = asyncio.Semaphore(3)

        async def limited_download(url):
            async with semaphore:
                return await download_and_process_image(session, url)

        download_tasks = [limited_download(url) for url in pics]
        local_paths_results = await asyncio.gather(
            *download_tasks, return_exceptions=True
        )
        local_paths = [
            path
            for path in local_paths_results
            if isinstance(path, str) and path and os.path.exists(path)
        ]
        log(f"✅ Скачано успешно: {len(local_paths)}/{len(pics)}")
        if not local_paths:
            return []
        upload_tasks = [upload_to_ftp(path) for path in local_paths]
        remote_paths_results = await asyncio.gather(
            *upload_tasks, return_exceptions=True
        )
        remote_paths = [
            path
            for path in remote_paths_results
            if isinstance(path, str) and path.startswith("https")
        ]
        for path in local_paths:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except:
                pass
        log(f"✅ Загружено на FTP: {len(remote_paths)}")
        return remote_paths


if __name__ == "__main__":

    async def main():
        test_urls = [
            "https://jvfurniture.eu/AfterbuyUploadService/DFC/1301315/Couchtisch/Couchtisch_Grau_DFC_1301315_main_226.png",
            "https://jvfurniture.eu/AfterbuyUploadService/VPH/12/Weinschrank/Weinschrank_Gold_VPH_12_main_97209.jfif",
            "https://jvfurniture.eu/2025_NEW_JOBS_OKTOBER2025/53_LENATES/0%20NEW/WM18/WM18%20%281%29.jpg",
        ]
        result = await process_pics(test_urls)
        log(result)

    asyncio.run(main())
