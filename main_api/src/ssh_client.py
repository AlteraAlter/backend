import paramiko
from typing import Optional
from main_api.src.logger import log


class SSHFileClient:
    def __init__(
        self,
        host: str,
        username: str,
        key_path: str,
        port: int = 22,
        timeout: int = 10,
    ):
        self.host = host
        self.username = username
        self.key_path = key_path
        self.port = port
        self.timeout = timeout

    def read_file(self, remote_path: str) -> Optional[str]:
        """
        Reads a file via SSH and returns its content.
        Returns None if file does not exist or error occurs
        """
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(policy=paramiko.AutoAddPolicy())

        try:
            client.connect(
                hostname=self.host,
                port=self.port,
                username=self.username,
                key_filename=self.key_path,
                timeout=self.timeout,
            )
            sftp = client.open_sftp()
            with sftp.open(remote_path, "r") as f:
                content = f.read().decode("utf-8")
            return content

        except FileNotFoundError:
            log(f"File was not found on server: {remote_path}", save=True)
            return None
        except Exception as e:
            log(f"SSH error ({remote_path}: {e})", save=True)
            return

        finally:
            try:
                client.close()
            except Exception:
                pass
