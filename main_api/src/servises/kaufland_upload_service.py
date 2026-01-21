from .json_mapper import map_json_item


class KauflandUploadService:
    def __init__(self, controller):
        self.controller = controller  # Kaufland Controller из каталога controller

    async def upload_single(self, raw_item: dict) -> bool:
        mapped = map_json_item(raw_item)
        return await self.controller.upload_single_product(mapped)

    async def upload_collection(self, raw_items: list[dict]) -> bool:
        mapped = [map_json_item(item) for item in raw_items]
        return await self.controller.upload_via_json(mapped)
