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
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo', 'ж': 'zh',
        'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o',
        'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u', 'ф': 'f', 'х': 'kh', 'ц': 'ts',
        'ч': 'ch', 'ш': 'sh', 'щ': 'sch', 'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu',
        'я': 'ya', 'А': 'A', 'Б': 'B', 'В': 'V', 'Г': 'G', 'Д': 'D', 'Е': 'E', 'Ё': 'Yo',
        'Ж': 'Zh', 'З': 'Z', 'И': 'I', 'Й': 'Y', 'К': 'K', 'Л': 'L', 'М': 'M', 'Н': 'N',
        'О': 'O', 'П': 'P', 'Р': 'R', 'С': 'S', 'Т': 'T', 'У': 'U', 'Ф': 'F', 'Х': 'Kh',
        'Ц': 'Ts', 'Ч': 'Ch', 'Ш': 'Sh', 'Щ': 'Sch', 'Ъ': '', 'Ы': 'Y', 'Ь': '', 'Э': 'E',
        'Ю': 'Yu', 'Я': 'Ya'
    }
    name = ''.join(cyrillic_to_latin.get(c, c) for c in name)
    name = name.replace("[^a-zA-Z0-9-_]", "")
    if not name:
        name = "image"
    return f"{name}{ext.lower()}"


async def download_and_process_image(session: aiohttp.ClientSession, url: str):
    async with http_semaphore:
        parsed = urlparse(url)
        host = parsed.netloc
        original_filename = os.path.basename(parsed.path)
        await rate_limiter.wait_if_needed(host)
        await asyncio.sleep(random.uniform(0.5, 2.0))

        name_part, ext_part = os.path.splitext(original_filename)
        clean_name = clean_filename(original_filename)
        ext_part = ext_part.lower().lstrip(".") or "jpg"
        if ext_part == "jpeg":
            ext_part = "jpg"

        cur_time = int(time.time())
        local_path = os.path.join(IMG_DIR, f"{clean_name}_{cur_time}.{ext_part}")

        MAX_FILE_SIZE = 9 * 1024 * 1024  # 9 MB
        MIN_WIDTH = 2098
        MIN_HEIGHT = 2098
        ALLOWED_EXTENSIONS = {"jpg", "png", "webp", "gif", "svg"}

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Connection': 'keep-alive',
                }
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=60), headers=headers,
                                       ssl=False) as resp:
                    if resp.status == 429:
                        retry_after = int(resp.headers.get('Retry-After', 60))
                        log(f"🔄 429 Too Many Requests, ждем {retry_after}с (попытка {attempt})")
                        await asyncio.sleep(retry_after + random.uniform(1, 3))
                        continue
                    if resp.status != 200:
                        raise Exception(f"Failed with status {resp.status}")
                    content = await resp.read()

                if ext_part == "svg":
                    async with aiofiles.open(local_path, "wb") as f:
                        await f.write(content)
                    return local_path

                image = Image.open(io.BytesIO(content))

                if ext_part not in ALLOWED_EXTENSIONS:
                    ext_part = "jpg"
                    local_path = os.path.join(IMG_DIR, f"{clean_name}_{cur_time}.{ext_part}")

                if image.mode in ("RGBA", "LA"):
                    background = Image.new("RGB", image.size, (255, 255, 255))
                    background.paste(image, mask=image.split()[-1] if image.mode == "RGBA" else image.getchannel('A'))
                    image = background
                    ext_part = "jpg"
                    local_path = os.path.join(IMG_DIR, f"{clean_name}_{cur_time}.{ext_part}")

                width, height = image.size
                
                # NOTE Хер знает как это работает от Никиты. Но оно работает. Пытался сделать по соответвии минимальным требованиям маркетплейса. Но тогда все ломается. Картинки не проходят проверку на маркетплейсе.
                # Проверяем размер файла и размеры изображения
                if len(content) > MAX_FILE_SIZE:
                    # Определяем масштаб для ресайза
                    scale_factor = 1.0
                    if width > MIN_WIDTH or height > MIN_HEIGHT:
                        # Сжимаем, чтобы меньшая сторона была не меньше MIN_WIDTH или MIN_HEIGHT
                        scale_factor = max(MIN_WIDTH / width, MIN_HEIGHT / height)
                        new_size = (int(width * scale_factor), int(height * scale_factor))
                        image = image.resize(new_size, Image.LANCZOS)
                        log(f"⚠️ Файл большой ({len(content) / 1024 / 1024:.2f} МБ), сжимаем до {new_size}")
                    elif width < MIN_WIDTH or height < MIN_HEIGHT:
                        # Расширяем, чтобы меньшая сторона была не меньше MIN_WIDTH или MIN_HEIGHT
                        scale_factor = max(MIN_WIDTH / width, MIN_HEIGHT / height)
                        new_size = (int(width * scale_factor), int(height * scale_factor))
                        image = image.resize(new_size, Image.LANCZOS)
                        log(f"⚠️ Файл большой ({len(content) / 1024 / 1024:.2f} МБ), расширяем до {new_size}")

                fmt = {"jpg": "JPEG", "png": "PNG", "webp": "WEBP", "gif": "GIF"}.get(ext_part, "JPEG")
                quality = 95
                max_attempts = 5

                # Проверяем размер после ресайза и снижаем качество, если нужно
                for i in range(max_attempts):
                    buffer = io.BytesIO()
                    image.save(buffer, format=fmt, quality=quality)
                    content = buffer.getvalue()

                    if len(content) <= MAX_FILE_SIZE or i == max_attempts - 1:
                        async with aiofiles.open(local_path, "wb") as f:
                            await f.write(content)
                        break

                    # Снижаем качество, если файл всё ещё большой
                    quality = int(quality * 0.85)  # Уменьшаем качество на 15%
                    log(f"⚠️ Файл всё ещё большой ({len(content) / 1024 / 1024:.2f} МБ), снижаем качество до {quality}")

                if os.path.getsize(local_path) > MAX_FILE_SIZE:
                    os.remove(local_path)
                    raise Exception(f"Не удалось уменьшить файл до {MAX_FILE_SIZE / 1024 / 1024:.2f} МБ")

                log(f"✅ Успешно обработано: {original_filename}")
                return local_path

            except Exception as e:
                log(f"[{url}] Ошибка при скачивании (попытка {attempt}/{MAX_RETRIES}): {e}")
                if attempt == MAX_RETRIES:
                    return None
                delay = (2 ** attempt) + random.uniform(1, 5)
                await asyncio.sleep(delay)


async def upload_to_ftp(local_path: str):
    filename = os.path.basename(local_path)
    log(f"Путь до файла: {local_path}")
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            async with ftp_semaphore:
                async with aioftp.Client.context(
                        host=FTP_HOST,
                        user=FTP_USERNAME,
                        password=FTP_PASSWORD,
                        port=21
                ) as client:
                    try:
                        await client.change_directory(FTP_REMOTE_DIR)
                        await client.upload(local_path)
                        log(f"Загрузили {filename} в {FTP_REMOTE_DIR}")
                        return f"https://automatonsoft.de/kaufland/{filename}"
                    except ConnectionResetError as e:
                        log(f"⚠️ ConnectionResetError при загрузке {filename} (попытка {attempt}): {e}")
                        if attempt == max_retries:
                            raise
                        await asyncio.sleep(2 ** attempt * random.uniform(0.1, 1))
                    except Exception as e:
                        log(f"❌ Ошибка FTP для {filename} (попытка {attempt}): {e}")
                        if attempt == max_retries:
                            raise
                        await asyncio.sleep(2 ** attempt * random.uniform(0.1, 1))
        except Exception as e:
            log(f"❌ Не удалось установить FTP соединение (попытка {attempt}): {e}")
            if attempt == max_retries:
                raise
            await asyncio.sleep(5 * attempt * random.uniform(0.1, 1))
    raise Exception(f"Не удалось загрузить {filename} после {max_retries} попыток")


async def process_pics(pics: list[str]):
    connector = aiohttp.TCPConnector(limit=5, limit_per_host=2, ttl_dns_cache=300, use_dns_cache=True)
    timeout = aiohttp.ClientTimeout(total=120, connect=30)
    async with aiohttp.ClientSession(connector=connector, timeout=timeout, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}) as session:
        semaphore = asyncio.Semaphore(3)

        async def limited_download(url):
            async with semaphore:
                return await download_and_process_image(session, url)

        download_tasks = [limited_download(url) for url in pics]
        local_paths_results = await asyncio.gather(*download_tasks, return_exceptions=True)
        local_paths = [path for path in local_paths_results if isinstance(path, str) and path and os.path.exists(path)]
        log(f"✅ Скачано успешно: {len(local_paths)}/{len(pics)}")
        if not local_paths:
            return []
        upload_tasks = [upload_to_ftp(path) for path in local_paths]
        remote_paths_results = await asyncio.gather(*upload_tasks, return_exceptions=True)
        remote_paths = [path for path in remote_paths_results if isinstance(path, str) and path.startswith('https')]
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
            "https://jvfurniture.eu/2025_NEW_JOBS_OKTOBER2025/53_LENATES/0%20NEW/WM18/WM18%20%281%29.jpg"
        ]
        result = await process_pics(test_urls)
        log(result)


    asyncio.run(main())