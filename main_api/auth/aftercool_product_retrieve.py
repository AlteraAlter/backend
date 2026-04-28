import httpx

class AftercoolProductRetrieveService:
    def __init__(self, aftercool_base_url: str, session_cookie: str):
        self.aftercool_base_url = aftercool_base_url
        self.session_cookie = session_cookie
    
    async def get_product(self, product_id: str) -> dict:
        url = f"{self.aftercool_base_url}/api/products"
        headers = {"Cookie": f"session={self.session_cookie}"}
        params = {"q": product_id}
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, params=params)
            if response.status_code == 200:
                return response.json()
            else:
                return {
                    "success": False,
                    "product": None,
                }