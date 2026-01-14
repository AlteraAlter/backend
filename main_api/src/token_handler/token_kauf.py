import asyncio
import time
from functools import wraps
import aiohttp


async def post_request(session, url, headers, data):
    """
        Универсальная функция для POST-запросов
    """
    try:
        async with session.post(url, headers=headers, json=data) as response:
            json_response = await response.json()
            return json_response
    except aiohttp.ClientError as e:
        print(f"Error при запросе к {url}: {e}")
        raise


async def get_request(session, url, headers):
    """
        Универсальная функция для GET-запросов
    """
    try:
        async with session.get(url, headers=headers) as response:
            json_response = await response.json()
            return json_response
    except aiohttp.ClientError as e:
        print(f"Error при запросе к {url}: {e}")
        raise


def token_required(f):
    """
        Декоратор для проверки и обновления токенов
    """

    @wraps(f)
    async def decorated(*args, **kwargs):
        async with aiohttp.ClientSession() as session:
            "Логика авторизации в Kaufland API"

            return await f(*args, **kwargs)
    return decorated


@token_required
async def main(version):
    pass

if __name__ == "__main__":
    asyncio.run(main(version="xl"))
