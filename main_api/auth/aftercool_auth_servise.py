import httpx

class AftercoolAuthService:
    def __init__(self, aftercool_base_url: str, username: str, password: str):
        self.aftercool_base_url = aftercool_base_url
        self.username = username
        self.password = password
        self.session = None
    
    async def authenticate(self) -> dict:
        url = f"{self.aftercool_base_url}/auth/login"
        payload = {"username": self.username, "password": self.password}
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload)
            if response.status_code == 200:
                self.session = response.cookies.get("session")
                return {"success": True, "session": self.session}
            else:
                return {
                    "success": False,
                    "session": None,
                }
         
async def main():
    aftercool_base_url = "https://aftercool.de"
    username = "Miras"
    password = "Miras112112"
    
    auth_service = AftercoolAuthService(aftercool_base_url, username, password)
    auth_result = await auth_service.authenticate()
    
    if auth_result["success"]:
        print(f"Authenticated successfully. Session: {auth_result['session']}")
    else:
        print("Authentication failed.")         
         
                
if __name__ == "__main__":
    import asyncio
    asyncio.run(main())