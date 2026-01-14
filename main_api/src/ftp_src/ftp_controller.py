# import asyncio
# import random
# import time
#
# import aiohttp
# import aiofiles
# import os
# import io
# from PIL import Image
# from urllib.parse import urlparse
# import aioftp
# from slugify import slugify
#
# from config import FTP_HOST, FTP_PASSWORD, FTP_USERNAME
#
# BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# IMG_DIR = os.path.join(BASE_DIR, "media", "imgs")
# os.makedirs(IMG_DIR, exist_ok=True)
#
# FTP_REMOTE_DIR = "/automatonsoft.de/kaufland/"
#
# MIN_WIDTH = 2098
# MIN_HEIGHT = 2098
# MAX_FILE_SIZE = 9 * 1024 * 1024  # 9 MB
# MAX_RETRIES = 3
# TIMEOUT = 60
#
# ftp_semaphore = asyncio.Semaphore(2)  # максимум 5 соединений одновременно
#
# ALLOWED_EXTENSIONS = {"jpg", "png", "gif", "svg", "webp"}
#
# def random_number():
#     return random.randint(1, 10) // 10
#
#
# def clean_filename(filename):
#     """Аналог slugify, адаптированный из main.js"""
#     name, ext = os.path.splitext(filename)
#     name = name.replace(" ", "-")
#     name = "".join(c for c in name if c.isalnum() or c in "-_")
#
#     cyrillic_to_latin = {
#         'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo', 'ж': 'zh',
#         'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o',
#         'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u', 'ф': 'f', 'х': 'kh', 'ц': 'ts',
#         'ч': 'ch', 'ш': 'sh', 'щ': 'sch', 'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu',
#         'я': 'ya', 'А': 'A', 'Б': 'B', 'В': 'V', 'Г': 'G', 'Д': 'D', 'Е': 'E', 'Ё': 'Yo',
#         'Ж': 'Zh', 'З': 'Z', 'И': 'I', 'Й': 'Y', 'К': 'K', 'Л': 'L', 'М': 'M', 'Н': 'N',
#         'О': 'O', 'П': 'P', 'Р': 'R', 'С': 'S', 'Т': 'T', 'У': 'U', 'Ф': 'F', 'Х': 'Kh',
#         'Ц': 'Ts', 'Ч': 'Ch', 'Ш': 'Sh', 'Щ': 'Sch', 'Ъ': '', 'Ы': 'Y', 'Ь': '', 'Э': 'E',
#         'Ю': 'Yu', 'Я': 'Ya'
#     }
#     name = ''.join(cyrillic_to_latin.get(c, c) for c in name)
#     name = name.replace("[^a-zA-Z0-9-_]", "")
#     if not name:
#         name = "image"
#     return f"{name}{ext.lower()}"
#
#
# async def download_and_process_image(session: aiohttp.ClientSession, url: str):
#     """
#     Скачивает изображение по URL и приводит к нужным параметрам:
#     - Разрешение минимум 2048×2048
#     - Размер файла максимум 10 MB
#     - Форматы: .jpg, .png, .gif, .svg, .webp
#     - jpeg → jpg
#     - Перезаписывает файл, если имя совпадает
#     """
#     async with ftp_semaphore:
#         parsed = urlparse(url)
#         original_filename = os.path.basename(parsed.path)
#
#         # Имя файла
#         name_part, ext_part = os.path.splitext(original_filename)
#         clean_name = clean_filename(original_filename)  # Используем кастомную функцию
#         ext_part = ext_part.lower().lstrip(".") or "jpg"
#         if ext_part == "jpeg":
#             ext_part = "jpg"
#
#         os.makedirs(IMG_DIR, exist_ok=True)
#         cur_time = int(time.time())
#         local_path = os.path.join(IMG_DIR, f"{clean_name}{cur_time}.{ext_part}")
#
#         for attempt in range(1, MAX_RETRIES + 1):
#             try:
#                 async with session.get(url, timeout=TIMEOUT) as resp:
#                     if resp.status != 200:
#                         raise Exception(f"Failed with status {resp.status}")
#                     content = await resp.read()
#
#                 # Проверка размера
#                 if len(content) > MAX_FILE_SIZE:
#                     raise Exception(f"File too large: {len(content)/1024/1024:.2f} MB")
#
#                 # SVG → сохраняем как есть
#                 if ext_part == "svg":
#                     with open(local_path, "wb") as f:
#                         f.write(content)
#                     return local_path
#
#                 # Обработка растровых изображений
#                 image = Image.open(io.BytesIO(content))
#
#                 # Если формат не в списке — принудительно jpg
#                 if ext_part not in ALLOWED_EXTENSIONS:
#                     ext_part = "jpg"
#                     local_path = os.path.join(IMG_DIR, f"{clean_name}{cur_time}.{ext_part}")
#
#                 # Прозрачность → белый фон
#                 if image.mode in ("RGBA", "LA"):
#                     background = Image.new("RGB", image.size, (255, 255, 255))
#                     background.paste(image, mask=image.split()[-1])
#                     image = background
#                     ext_part = "jpg"
#                     local_path = os.path.join(IMG_DIR, f"{clean_name}{cur_time}.{ext_part}")
#
#                 # Масштабирование до минимальных размеров
#                 width, height = image.size
#                 if width < MIN_WIDTH or height < MIN_HEIGHT:
#                     scale_factor = max(MIN_WIDTH / width, MIN_HEIGHT / height)
#                     new_size = (int(width * scale_factor), int(height * scale_factor))
#                     image = image.resize(new_size, Image.LANCZOS)
#
#                 # Определение формата
#                 fmt = {
#                     "jpg": "JPEG",
#                     "png": "PNG",
#                     "webp": "WEBP",
#                     "gif": "GIF"
#                 }.get(ext_part, "JPEG")
#
#                 # Сохраняем с перезаписью
#                 image.save(local_path, format=fmt, quality=95)
#
#                 # Проверяем финальный размер
#                 if os.path.getsize(local_path) > MAX_FILE_SIZE:
#                     os.remove(local_path)
#                     raise Exception("Processed file exceeds 10MB")
#
#                 return local_path
#
#             except Exception as e:
#                 print(f"[{url}] Ошибка при скачивании (попытка {attempt}/{MAX_RETRIES}): {e}")
#                 if attempt == MAX_RETRIES:
#                     return None
#                 await asyncio.sleep(2 * attempt * random_number())
#
#
#
# async def upload_to_ftp(local_path: str):
#     """
#     Загружает локальный файл на FTP в папку kaufland/
#     """
#     filename = os.path.basename(local_path)
#     print(f"Путь до файла: {local_path}\nИмя файла: {filename}")
#     max_retries = 3
#     for attempt in range(1, max_retries + 1):
#         try:
#             async with ftp_semaphore:
#                 async with aioftp.Client.context(
#                     host=FTP_HOST,
#                     user=FTP_USERNAME,
#                     password=FTP_PASSWORD,
#                     port=21
#                 ) as client:
#                     try:
#                         # Переходим в папку kaufland
#                         await client.change_directory(FTP_REMOTE_DIR)
#                         # Загружаем файл
#                         await client.upload(local_path)
#                         print(f"Загрузили {filename} в {FTP_REMOTE_DIR}")
#                         rem_path = f"https://automatonsoft.de/kaufland/{filename}"
#                         return rem_path
#                     except ConnectionResetError as e:
#                         print(f"⚠️ ConnectionResetError при загрузке {filename} (попытка {attempt}): {e}")
#                         if attempt == max_retries:
#                             raise
#                         await asyncio.sleep(2 ** attempt * random_number())  # Экспоненциальная задержка
#                     except Exception as e:
#                         print(f"❌ Ошибка FTP для {filename} (попытка {attempt}): {e}")
#                         if attempt == max_retries:
#                             raise
#                         await asyncio.sleep(2 ** attempt * random_number())
#         except Exception as e:
#             print(f"❌ Не удалось установить FTP соединение (попытка {attempt}): {e}")
#             if attempt == max_retries:
#                 raise
#             await asyncio.sleep(5 * attempt * random_number())
#     raise Exception(f"Не удалось загрузить {filename} после {max_retries} попыток")
#
# async def process_pics(pics: list[str]):
#     """
#     Основная функция: скачивает, обрабатывает и загружает картинки с ретраями.
#     """
#     async with aiohttp.ClientSession(
#             timeout=aiohttp.ClientTimeout(total=TIMEOUT),
#             connector=aiohttp.TCPConnector(limit=10, limit_per_host=5)
#     ) as session:
#         # Скачиваем все картинки
#         download_tasks = [download_and_process_image(session, url) for url in pics]
#         local_paths = await asyncio.gather(*download_tasks)
#         print("СКАЧАЛИ")
#         # Загружаем на FTP только успешно скачанные
#         upload_tasks = [upload_to_ftp(path) for path in local_paths if path]
#         remote_paths = await asyncio.gather(*upload_tasks)
#         return remote_paths
#
# # 📌 Пример использования
# if __name__ == "__main__":
#     async def main():
#         test_urls = [
#             "https://jvfurniture.eu/2025_NEW_JOBS_OKTOBER2025/45_HDFOCUS_CN/HDFOCUS/HDFOCUS_TECHNOLOGY_Part_1_11_12_Arslan/3.UNGROPED/25/1",
#             "https://jvfurniture.eu/AfterbuyUploadService/VPH/12/Weinschrank/Weinschrank_Gold_VPH_12_main_97209.jfif",
#             "https://jvfurniture.eu/2025_NEW_JOBS_OKTOBER2025/53_LENATES/0%20NEW/WM18/WM18%20%281%29.jpg"
#         ]
#         result = await process_pics(test_urls)
#         print(result)
#     asyncio.run(main())