from abc import ABC, abstractmethod


class ImageStorage(ABC):
    @abstractmethod
    async def upload(self, local_path: str) -> str:
        """
        Uploads local file and returns public URL.
        """
        raise NotImplementedError
