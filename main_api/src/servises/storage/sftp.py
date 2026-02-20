import os
import asyncssh
from main_api.src.logger import log

REMOTE_HOST = "217.11.76.91"
REMOTE_USER = "user"
REMOTE_DIR = "/srv/kaufland"
PUBLIC_BASE_URL = "https://automatonsoft.de/kaufland"


class SftpImageStorage:
    def __init__(self):
        self.host = REMOTE_HOST
        self.user = REMOTE_USER
        self.remote_dir = REMOTE_DIR
        self.public_base_url = PUBLIC_BASE_URL

    async def upload(self, local_path: str) -> str:
        filename = os.path.basename(local_path)
        remote_path = f"{self.remote_dir}/{filename}"

        log(f"=========>DEBUG<=========\n       remote_path = {remote_path}")
        try:
            async with asyncssh.connect(
                host=self.host,
                username=self.user,
                client_keys=["/root/.ssh/paramiko_django"],
            ) as conn:
                async with conn.start_sftp_client() as sftp:
                    await sftp.put(local_path, remote_path)
        except Exception as e:
            log(f"Error while upload: {e}")
        finally:
            log(f"✅ SFTP uploaded: {filename}")

        return f"{self.public_base_url}/{filename}"
