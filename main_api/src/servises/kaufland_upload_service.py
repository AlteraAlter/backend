from .json_mapper import map_json_item
from main_api.src.controller.kaufland_controller import KauflandController
import json

class KauflandUploadService:
    def __init__(self, controller):
        self.controller: KauflandController = (
            controller  # Kaufland Controller из каталога controller
        )

    async def upload_single(self, raw_item: dict, job_id: str | None = None) -> bool:
        mapped = map_json_item(raw_item)
        return await self.controller.upload_single_product(mapped, job_id=job_id)

    async def upload_collection(
        self,
        raw_items: list[dict],
        job_id: str | None = None,
        controller: str | None = None,
    ) -> bool:
        mapped = [map_json_item(item) for item in raw_items]
        return await self.controller.upload_via_json(mapped, job_id=job_id)
