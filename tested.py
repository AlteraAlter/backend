import paramiko
import os

key_path = os.path.expanduser("~/.ssh/id_ed25519Miraz")

key = paramiko.Ed25519Key.from_private_key_file(
    key_path,
    password="narutoshippuden45",
)
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(
    hostname="217.11.76.91",
    port=22,
    username="user",
    pkey=key,
    timeout=10,
)
