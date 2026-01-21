import os
import asyncio
import aioftp
from main_api.src.logger import log
from config import FTP_HOST, FTP_USERNAME, FTP_PASSWORD

FTP_REMOTE_DIR = "/automatonsoft.de/kaufland/"
FTP_PUBLIC_BASE_URL = "https://www.automatonsoft.de/kaufland"


class FtpImageStorage:
    def __init__(
        self,
        host: str = FTP_HOST,
        user: str = FTP_USERNAME,
        password: str = FTP_PASSWORD,
        remote_dir: str = FTP_REMOTE_DIR,
        public_base_url: str = FTP_PUBLIC_BASE_URL,
        max_retries: int = 3,
    ):
        self.host = host
        self.user = user
        self.password = password
        self.remote_dir = remote_dir
        self.public_base_url = public_base_url
        self.max_retries = max_retries
        self._semaphore = asyncio.Semaphore(2)

    async def upload(self, local_path: str) -> str | None:
        filename = os.path.basename(local_path)

        for attempt in range(1, self.max_retries + 1):
            try:
                async with aioftp.Client.context(
                    host=self.host, user=self.user, password=self.password, port=21
                ) as client:
                    await client.change_directory(self.remote_dir)
                    await client.upload(local_path)

                log(f"✅ FTP uploaded: {filename}")
                return f"{self.public_base_url}/{filename}"
            except Exception as e:
                log(f"❌ FTP error {attempt}/{self.max_retries}: {e}")
                if attempt == self.max_retries:
                    raise
                await asyncio.sleep(2**attempt)
