import os
import shutil
import asyncio


class LocalStorage:
    def __init__(self, file):
        self.file = file

    async def upload(self):
        filename = os.path.basename(self.file)
        return filename


async def main():
    file = "https://www.shutterstock.com/shutterstock/photos/2728618231/display_1500/stock-photo-close-up-of-the-tail-of-a-diving-humpback-whale-megaptera-novaeangliae-image-taken-in-the-graham-2728618231.jpg"
    strg = LocalStorage(file=file)
    print(await strg.upload())


if __name__ == "__main__":
    asyncio.run(main())
