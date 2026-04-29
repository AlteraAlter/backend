import httpx
from typing import Any

from requests import session
from main_api.src.logger import log


class AftercoolProductRetrieveService:
    def __init__(self, aftercool_base_url: str, session_cookie: str):
        self.aftercool_base_url = aftercool_base_url
        self.session_cookie = session_cookie
    
    async def get_product(self, product_id: str) -> dict[str, Any]:
        url = f"{self.aftercool_base_url}/api/products"
        headers = {"Cookie": f"session={self.session_cookie}"}
        params = {"q": product_id, "include_row": 1}

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, params=params)
            payload = response.json() if response.status_code == 200 else {}
            items = payload.get("items") if isinstance(payload, dict) else []

            if isinstance(items, list) and items:
                first_name = items[0].get("name") if isinstance(items[0], dict) else ""
                if first_name:
                    log(str(first_name))
                return {
                    "success": True,
                    "items": items,
                    "payload": payload,
                }

            return {
                "success": False,
                "items": [],
                "payload": payload if isinstance(payload, dict) else {},
            }


async def main():
    session = "eyJ1c2VyIjogeyJ1c2VybmFtZSI6ICJNaXJhcyIsICJyb2xlIjogInVzZXIifSwgImlhdCI6IDE3Nzc0NDg4NzZ9.afG3rA.DOkHTA7UsHhORwa86sATpawB7Zk"
    aftercool_base_url = "https://aftercool.de"
    product_id = "175494961"
    
    product_service = AftercoolProductRetrieveService(aftercool_base_url, session)
    
    product_result = await product_service.get_product(product_id)
    print(product_result)
    
if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
    