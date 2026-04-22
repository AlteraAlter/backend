from cmath import pi
import os
from pydoc import describe
import re
import math
import time
import hmac
import json
import random
import asyncio
from turtle import title
from typing import Any
from uuid import uuid4
import certifi
import aiohttp
import hashlib
from datetime import datetime
from aiohttp import ClientError
from django.conf import settings
from channels.layers import get_channel_layer
from numpy import int32
from config import (
    controllers_base,
    storefronts,
    XL_CONTACT_DATA,
    XL_MANUFACTURER,
    JV_CONTACT_DATA,
    JV_MANUFACTURER,
    SSH_HOST,
    SSH_USER,
    SSH_KEY_PATH,
)
import ssl
from aiolimiter import AsyncLimiter
from main_api.src.logger import log
from main_api.src.job_registry import (
    is_cancelled,
    clear_cancel,
    register_running_job,
    unregister_running_job,
    acquire_ean_lock,
    release_ean_lock,
)
from main_api.src.ssh_client import SSHFileClient
from main_api.src.extracter import adapt_html_description
from main_api.src.servises.pic_pipline import process_pics
from main_api.src.utils.timer import log_time
from main_api.src.gpt.gpt_helper import generate_description, generate_seo
from aiohttp import ClientSession
from rest_framework import status

try:
    _GLOBAL_API_RATE = max(1, int(os.getenv("KAUFLAND_API_RATE_PER_SEC", "60")))
except ValueError:
    _GLOBAL_API_RATE = 60
_GLOBAL_API_LIMITER = AsyncLimiter(_GLOBAL_API_RATE, time_period=1)

try:
    _GLOBAL_REQUEST_DELAY_SEC = max(
        0.0, float(os.getenv("KAUFLAND_API_REQUEST_DELAY_SEC", "0.08"))
    )
except ValueError:
    _GLOBAL_REQUEST_DELAY_SEC = 0.08
_GLOBAL_REQUEST_DELAY_LOCK = asyncio.Lock()
_GLOBAL_LAST_REQUEST_AT = 0.0

try:
    _WS_PROGRESS_INTERVAL_SEC = max(
        0.0, float(os.getenv("WS_PROGRESS_INTERVAL_SEC", "60"))
    )
except ValueError:
    _WS_PROGRESS_INTERVAL_SEC = 60
try:
    _WS_PROGRESS_EVERY = max(0, int(os.getenv("WS_PROGRESS_EVERY", "0")))
except ValueError:
    _WS_PROGRESS_EVERY = 0


EMBEDDED_ENTITIES = ["category", "category_basic", "units"]


class KauflandController:
    """
    Класс для взаимодействия с кауфлендом
    """

    def __init__(self, session: ClientSession, version):
        # Shared limiter for the whole process to avoid per-job rate multiplication.
        self.limiter = _GLOBAL_API_LIMITER
        self.session = session
        self.version = version
        self.channel_layer = get_channel_layer()
        self.retries = 3
        self.backoff = 2
        try:
            self.upload_batch_size = max(1, int(os.getenv("UPLOAD_BATCH_SIZE", "6")))
        except ValueError:
            self.upload_batch_size = 6
        self.base_api_url = "https://sellerapi.kaufland.com/v2"
        self._ssh_client = None  # Коннекшн к ншашему серверу

        # Мини кэшируемая система
        self._ean_cache = {
            "unit_ids": {},
            "product_ids": {},
            "main_data": {},
        }

    @staticmethod
    def _should_emit_progress(
        *,
        processed: int,
        total: int,
        last_emit_at: float | None,
        interval_sec: float = _WS_PROGRESS_INTERVAL_SEC,
        every_n: int = _WS_PROGRESS_EVERY,
    ) -> bool:
        if total > 0 and processed >= total:
            return True
        if processed <= 0:
            return False
        if every_n > 0 and processed % every_n == 0:
            return True
        now = time.monotonic()
        if last_emit_at is None:
            return True
        return (now - last_emit_at) >= max(0.0, interval_sec)

    def _get_ssh_client(self):
        """
        Lazy SSH client initialization
        Created once per controller instance
        """
        if self._ssh_client == None:
            self._ssh_client = SSHFileClient(
                host=SSH_HOST, username=SSH_USER, key_path=SSH_KEY_PATH
            )
        return self._ssh_client

    async def _apply_inter_request_delay(self) -> None:
        global _GLOBAL_LAST_REQUEST_AT
        if _GLOBAL_REQUEST_DELAY_SEC <= 0:
            return
        async with _GLOBAL_REQUEST_DELAY_LOCK:
            now = time.monotonic()
            wait_seconds = (_GLOBAL_LAST_REQUEST_AT + _GLOBAL_REQUEST_DELAY_SEC) - now
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)
            _GLOBAL_LAST_REQUEST_AT = time.monotonic()

    # NOTE: НЕ ТРОГАТЬ!!!
    @staticmethod
    def _sign_request(method, uri, body, timestamp, secret_key):
        """
        Функция для генерирования нового HMAC делается для
        безопасности использования в Kaufland, для КАЖДОГО запроса
        """
        if isinstance(body, dict):
            body = json.dumps(body, separators=(",", ":"))  # важно без пробелов
        elif body is None:
            body = ""
        plain_text = "\n".join([method, uri, body, str(timestamp)])
        digest_maker = hmac.new(secret_key.encode(), None, hashlib.sha256)
        digest_maker.update(plain_text.encode())
        return digest_maker.hexdigest()

    # NOTE: НЕ ТРОГАТЬ!!!
    async def _get_headers(self, url, body, method):
        if body is None:
            body = ""
        timenow = str(int(time.time()))
        controller = self.version
        client_key = controllers_base[controller]["client_key"]
        secret_key = controllers_base[controller]["secret_key"]
        signed_key = self._sign_request(
            method=method, uri=url, body=body, timestamp=timenow, secret_key=secret_key
        )
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "Inhouse_development",
            "Shop-Timestamp": timenow,
            "Shop-Client-Key": client_key,
            "Shop-Signature": signed_key,
        }
        return headers

    # NOTE: НЕ ТРОГАТЬ!!!
    async def _universal_request(self, method, url, body=None, params=None) -> Any:
        """
        Универсальная функция для выполнения реквестов для любых
        методов
        """
        ssl_cert = ssl.create_default_context(cafile=certifi.where())

        if body is not None and body != "":
            if isinstance(body, dict):
                serialized_body = json.dumps(body, separators=(",", ":"))
            else:
                serialized_body = body
        else:
            serialized_body = ""

        # Генерируем заголовки с использованием именно serialized_body
        for attempt in range(1, self.retries + 1):
            headers = await self._get_headers(url, serialized_body, method=method)

            async with self.limiter:
                await self._apply_inter_request_delay()
                if method == "GET":
                    async with self.session.get(
                        url=url, headers=headers, params=params, ssl=ssl_cert
                    ) as response:
                        if response.status == status.HTTP_200_OK:
                            return await response.json()
                        elif response.status == status.HTTP_404_NOT_FOUND:
                            return {
                                "message": "not found",
                                "status": status.HTTP_404_NOT_FOUND,
                                "data": None,
                            }
                        return await response.json()

                elif method == "POST":
                    async with self.session.post(
                        url=url, headers=headers, data=serialized_body, ssl=ssl_cert
                    ) as response:
                        # response.raise_for_status()
                        return await response.json()
                elif method == "PUT":
                    async with self.session.put(
                        url=url, headers=headers, data=serialized_body, ssl=ssl_cert
                    ) as response:
                        # response.raise_for_status()
                        return await response.json()
                elif method == "DELETE":
                    async with self.session.delete(
                        url=url, headers=headers, json=body, ssl=ssl_cert
                    ) as response:
                        if (
                            response.status == 204
                            or response.status == 200
                            or response.status == 404
                        ):
                            return True
                        elif attempt == self.retries:
                            return False
                elif method == "PATCH":
                    async with self.session.patch(
                        url=url, headers=headers, data=serialized_body, ssl=ssl_cert
                    ) as response:
                        if response.status == 200:
                            return {"message": "success"}
                        elif response.status == 404:
                            return {"message": "not found"}
                        else:
                            return {
                                "message": "something went wrong",
                                "status": response.status,
                                "response": response,
                            }

    @staticmethod
    async def get_exchange_rate(currency: str = "PLN") -> float:
        """
        Возвращает курс EUR -> currency.
        """
        currency_dict = {"PLN": 4.7, "CZK": 25.4, "ITP": 1.05}
        return currency_dict[currency]

    @staticmethod
    def format_price(price: float) -> int:
        """
        Округляет цену в большую сторону и заменяет последнюю цифру на 9.
        Например, 12.34 -> 19.99, 56.78 -> 59.99
        Args:
            price (float): Исходная цена.
        Returns:
            int: Отформатированная цена в центах.
        """
        # округляем в большую сторону
        price_up = math.ceil(price)

        # отбрасываем последнюю цифру и прибавляем 9
        return ((price_up // 10) * 10 + 9) * 100

    async def _make_price(self, storefront, price):
        """
        Функция которая создает цену взависимости от страны
        Принимает страну и цену
        """
        if storefront == "cz":
            rate = await self.get_exchange_rate("CZK")
            total_price = int(self.format_price(rate * price))
        elif storefront == "pl":
            rate = await self.get_exchange_rate("PLN")
            total_price = int(self.format_price(rate * price))
        elif storefront == "fr" or storefront == "it":
            rate = await self.get_exchange_rate(
                "ITP"
            )  # ITP Increased Tax Price = EUR_1.05
            total_price = int(self.format_price(price * rate))
        else:
            total_price = int(self.format_price(price))
        return total_price

    @staticmethod
    async def status_processing(tasks: list) -> bool:
        """
        Функция для обработки статуса всех тасков.
        Если все успешно возвращает True иначе False.
        """
        bool_list = []
        for elem in range(0, len(tasks), 10):
            new_tasks = tasks[elem : elem + 10]
            result = await asyncio.gather(*new_tasks)
            if all(result):
                bool_list.append(True)
            else:
                bool_list.append(False)
        if all(bool_list):
            return True
        return False

    async def _fetch_unit_id_by_ean(self, ean):
        """
        Функция которая собирает unit_id
        о продукте по его EAN со всех стран.
        Так же кешируема для более быстрого поиска
        """
        if ean in self._ean_cache["unit_ids"]:
            return self._ean_cache["unit_ids"][ean]

        async def fetch_storefront_unit_id(storefront):
            url = f"{self.base_api_url}/products/ean/{ean}?storefront={storefront}&embedded=units"
            result = await self._universal_request(method="GET", url=url)

            if not isinstance(result, dict):
                return storefront, None

            data = result.get("data") or {}
            units = data.get("units") or [{}]
            unit_id = units[0].get("id_unit", None)

            return storefront, unit_id

        final_res = {}
        try:
            fetched = await asyncio.gather(
                *(fetch_storefront_unit_id(storefront) for storefront in storefronts)
            )
            final_res = {
                storefront: unit_id for storefront, unit_id in fetched if unit_id
            }
        except Exception as e:
            log(f"_fetch_unit_id_by_ean failed ean={ean} error={e}", save=True)
        self._ean_cache["unit_ids"][ean] = final_res
        return final_res

    async def _fetch_product_id_by_ean(self, ean):
        """
        Функция которая собирает product_id
        о продукте по его EAN со всех стран
        """
        if ean in self._ean_cache["product_ids"]:
            return self._ean_cache["product_ids"][ean]

        async def fetch_storefront_product_id(storefront):
            log(f"[{ean}] Start of parsing product's product_id")
            url = f"{self.base_api_url}/products/ean/{ean}?storefront={storefront}&embedded=units"
            result = await self._universal_request(method="GET", url=url)
            log(f"[{ean}] End of parsing product_id. Result is -----> {result}")
            if not isinstance(result, dict):
                log(f"[{ean} Error happend while fetching]")
                return storefront, ""
            data = result.get("data") or {}
            product_id = data.get("id_product", "")
            return storefront, product_id

        fetched = await asyncio.gather(
            *(fetch_storefront_product_id(storefront) for storefront in storefronts)
        )
        final_res = {
            storefront: product_id for storefront, product_id in fetched if product_id
        }
        self._ean_cache["product_ids"][ean] = final_res
        return final_res

    async def _add_unit_id(self, ean, price, delivery, target_storefronts=None):
        """
        Create a unit for a product in Kaufland.
        """
        if target_storefronts is None:
            target_storefronts = storefronts

        async def add_unit_for_storefront(storefront):
            url = f"{self.base_api_url}/units?storefront={storefront}&embedded=eco_participation"
            formatted_price = await self._make_price(storefront=storefront, price=price)

            body = {
                "amount": 20,
                "handling_time": delivery,
                "listing_price": formatted_price,
                "ean": str(ean),
                "id_offer": f"{ean}",
                "condition": "NEW",
            }

            log(f"[{ean}] <====Creating an offer====>")

            result = await self._universal_request("POST", url, body=body)
            if not isinstance(result, dict):
                log(
                    f"add_unit failed ean={ean} storefront={storefront} response_type={type(result).__name__}",
                    save=True,
                )
                return False

            data = result.get("data") or {}
            if data.get("status", "") == "AVAILABLE":
                return True
            log(
                f"add_unit failed ean={ean} storefront={storefront} response={result} body={json.dumps(body, ensure_ascii=False)}",
                save=True,
            )
            return False

        bool_list = await asyncio.gather(
            *(add_unit_for_storefront(storefront) for storefront in target_storefronts)
        )
        return all(bool_list)

    async def _fetch_main_data_by_ean(self, ean):
        """
        Функция которая собирает unit_id, title, price
        """

        if ean in self._ean_cache["main_data"]:
            return self._ean_cache["main_data"][ean]

        async def fetch_storefront_main_data(storefront):
            url = f"{self.base_api_url}/products/ean/{ean}?storefront={storefront}&embedded=units"
            result = await self._universal_request(method="GET", url=url)
            if not isinstance(result, dict):
                return None
            if result.get("status") == status.HTTP_404_NOT_FOUND:
                return None
            data = result.get("data") or {}
            units = data.get("units") or []
            id_unit = units[0].get("id_unit") if units else None
            if id_unit:
                title = data.get("title")
                price = float(units[0].get("price")) / 100
                storefront = data.get("storefront")
                return {
                    "ean": ean,
                    "title": title,
                    "price": price,
                    "storefront": storefront,
                }
            return None

        fetched = await asyncio.gather(
            *(fetch_storefront_main_data(storefront) for storefront in storefronts)
        )
        final_res = [item for item in fetched if item]
        self._ean_cache["main_data"][ean] = final_res
        return final_res

    # async def _send_progress(self, ean: str, stage: str, extra: dict | None = None):
    #     channel_layer = get_channel_layer()

    #     await channel_layer.group_send(
    #         "upload_progress",
    #         {
    #             "type": "upload_progress",
    #             "ean": ean,
    #             "stage": stage,
    #             "controller": self.version,
    #             "extra": extra or {},
    #             "timestamp": datetime.now().isoformat(),
    #         },
    #     )

    async def _send_progress(
        self,
        job_id: str,
        event: str,
        payload: dict | None = None,
        info: str | None = None,
    ):
        if not job_id:
            return
        await self._ws_message_send(
            group_name=f"{job_id}_upload",
            job_id=job_id,
            event=event,
            payload=payload,
            info=info,
        )

    async def _send_task_progress(
        self,
        job_id: str | None,
        task: str,
        event: str,
        payload: dict | None = None,
        info: str | None = None,
    ):
        if not job_id:
            return
        payload_with_task = dict(payload or {})
        payload_with_task.setdefault("task", task)
        await self._ws_message_send(
            group_name=f"{job_id}_{task}",
            job_id=job_id,
            event=event,
            payload=payload_with_task,
            info=info,
        )

    async def _ws_message_send(
        self,
        group_name: str,
        job_id: str,
        event: str,
        payload: dict | None = None,
        info: str | None = None,
    ):
        if not self.channel_layer:
            return
        await self.channel_layer.group_send(
            group_name,
            {
                "type": "ws_message",
                "job_id": job_id,
                "event": event,
                "payload": payload,
                "info": info,
                "timestamp": datetime.now().isoformat(),
            },
        )

    @staticmethod
    def _normalize_value(value):
        if isinstance(value, list):
            return ", ".join([str(v) for v in value if v is not None])
        return value

    def _build_item_payload(self, elem: dict | None) -> dict:
        if not isinstance(elem, dict):
            return {
                "ean": None,
                "article": None,
                "price": None,
                "size": None,
                "color": None,
                "material": None,
                "fabric": None,
            }
        return {
            "ean": elem.get("ean"),
            "article": elem.get("article"),
            "price": elem.get("price"),
            "size": self._normalize_value(elem.get("size")),
            "color": self._normalize_value(elem.get("color")),
            "material": self._normalize_value(elem.get("material")),
            "fabric": elem.get("fabric"),
        }

    async def _emit_progress_event(
        self,
        job_id: str | None,
        event: str,
        payload: dict | None = None,
        info: str | None = None,
    ):
        if not job_id:
            return
        await self._send_progress(job_id, event, payload=payload, info=info)

    async def _emit_stage(
        self,
        job_id: str | None,
        ean: str | None,
        item: dict | None,
        stage: str,
        message: str | None = None,
        status: str = "running",
        extra: dict | None = None,
    ):
        payload = {
            "status": status,
            "ean": ean,
            "item": item,
            "stage": stage,
        }
        if message:
            payload["message"] = message
        if extra:
            payload["extra"] = extra
        await self._emit_progress_event(job_id, "progress", payload=payload)

    async def _emit_ean_status(
        self,
        job_id: str | None,
        status: str,
        ean: str | None,
        item: dict | None,
        stage: str | None = None,
        message: str | None = None,
        detail: str | None = None,
    ):
        payload = {
            "status": status,
            "ean": ean,
            "item": item,
        }
        if stage:
            payload["stage"] = stage
        if message:
            payload["message"] = message
        if detail:
            payload["detail"] = detail
        await self._emit_progress_event(job_id, "ean_completed", payload=payload)

    async def _update_price_by_unit_id(
        self,
        ean,
        price,
        new_unit_id: dict[str, str] | None = None,
    ):
        """
        Update product price by unit_id.
        """
        channel_layer = get_channel_layer()
        final_res = (
            new_unit_id
            if new_unit_id is not None
            else await self._fetch_unit_id_by_ean(ean)
        )

        if final_res:
            bool_list = []
            for storefront, unit_id in final_res.items():
                url = f"{self.base_api_url}/units/{unit_id}?storefront={storefront}&embedded=eco_participation"
                total_price = await self._make_price(storefront=storefront, price=price)
                payload = {"listing_price": total_price}
                result = await self._universal_request(
                    method="PATCH", url=url, body=payload
                )
                message = result["message"]

                if message == "success":
                    await channel_layer.group_send(
                        "price_updates",  # Group
                        {
                            "type": "price_update",
                            "ean": ean,
                            "new_price": total_price / 100,
                            "storefront": storefront,
                            "timestamp": datetime.now().isoformat(),
                            "result": message,
                        },
                    )
                    bool_list.append(True)
                elif message == "not found":
                    await channel_layer.group_send(
                        "price_updates",  # Group
                        {
                            "type": "price_update",
                            "ean": ean,
                            "new_price": 0,
                            "old_price": 0,
                            "storefront": storefront,
                            "timestamp": datetime.now().isoformat(),
                            "result": message,
                        },
                    )
                    bool_list.append(True)
                else:
                    await channel_layer.group_send(
                        "price_updates",  # Group
                        {
                            "type": "price_update",
                            "ean": ean,
                            "new_price": 0,
                            "old_price": 0,
                            "storefront": storefront,
                            "timestamp": datetime.now().isoformat(),
                            "result": message,
                        },
                    )
                    bool_list.append(False)
            return all(bool_list)
        await channel_layer.group_send(
            "price_updates",  # Group
            {
                "type": "price_update",
                "ean": ean,
                "new_price": 0,
                "old_price": 0,
                "storefront": "all",
                "timestamp": datetime.now().isoformat(),
                "result": {"message": "product not found"},
            },
        )
        return True

    async def _delete_product_by_unit_id(
        self, ean: str, job_id: str | None = None
    ) -> bool:
        """
        Delete products by unit_id.
        """
        channel_layer = get_channel_layer()
        logs_dir = os.path.join(settings.MEDIA_ROOT, "logs")
        logs_file_path = os.path.join(logs_dir, "delete_products_logs.csv")
        os.makedirs(logs_dir, exist_ok=True)

        final_res = await self._fetch_unit_id_by_ean(ean)
        if final_res:
            bool_list = []
            for storefront, unit_id in final_res.items():
                url = f"{self.base_api_url}/units/{unit_id}?storefront={storefront}"
                result = await self._universal_request(method="DELETE", url=url)
                if result:
                    bool_list.append(True)
                    with open(logs_file_path, "a", encoding="utf-8") as file:
                        file.write(
                            f"\nDeleted product {self.version} EAN: {ean} storefront: {storefront}\n"
                        )
                else:
                    bool_list.append(False)
                    log(
                        f"delete failed ean={ean} storefront={storefront} unit_id={unit_id}",
                        save=True,
                    )
                    with open(logs_file_path, "a", encoding="utf-8") as file:
                        file.write(
                            f"\nDelete failed {self.version} EAN: {ean} storefront: {storefront}\n"
                        )

                await channel_layer.group_send(
                    "delete_group",
                    {
                        "type": "delete_progress",
                        "message": (
                            {"info": "success"} if result else {"info": "fail"}
                        ),
                        "controller": self.version,
                        "ean": ean,
                        "storefront": storefront,
                    },
                )
                await self._send_task_progress(
                    job_id,
                    "delete",
                    "storefront_result",
                    payload={
                        "controller": self.version,
                        "ean": ean,
                        "storefront": storefront,
                        "result": "success" if result else "fail",
                    },
                )

            return all(bool_list)

        log(f"delete no_unit_ids ean={ean}", save=True)

        await channel_layer.group_send(
            "delete_group",
            {
                "type": "delete_message",
                "message": {"info": "no_unit_ids"},
                "controller": self.version,
                "ean": ean,
                "storefront": "all",
            },
        )
        await self._send_task_progress(
            job_id,
            "delete",
            "storefront_result",
            payload={
                "controller": self.version,
                "ean": ean,
                "storefront": "all",
                "result": "no_unit_ids",
            },
        )

        log(f"delete ean_not_found ean={ean}", save=True)
        with open(logs_file_path, "a", encoding="utf-8") as file:
            file.write(f"\nEAN not found: {ean}\n")
        return True

    async def _check_product_by_unit_id(self, ean, job_id: str | None = None):
        """
        Check a single product by unit_id.
        """
        final_res = await self._fetch_main_data_by_ean(ean)
        if final_res:
            await self._send_task_progress(
                job_id,
                "checker",
                "item",
                payload={"controller": self.version, "ean": ean, "items": final_res},
            )
            storefronts = sorted(
                {item.get("storefront") for item in final_res if item.get("storefront")}
            )
            return {
                "ean": ean,
                "found": True,
                "storefronts": storefronts,
                "items": final_res,
                "message": None,
            }
        await self._send_task_progress(
            job_id,
            "checker",
            "item",
            payload={"controller": self.version, "ean": ean, "items": []},
            info="not found",
        )
        return {
            "ean": ean,
            "found": False,
            "storefronts": [],
            "items": [],
            "message": "not found",
        }

    async def _category_selector(self, article, price, ean, description):
        """
        Функция которая определяет категорию на основе article
        и его description
        """
        item_for_category_js = {
            "item": {
                "title": article,
                "description": description,
                "manufacturer": "AEA GmbH & Co. KG",
            },
            "price": price,
        }
        url_category = (
            f"{self.base_api_url}/categories/decide?storefront=de&locale=de-DE"
        )

        result_category = await self._universal_request(
            method="POST", url=url_category, body=item_for_category_js
        )
        if "data" not in result_category:
            log(
                f"ERROR WITH CATEGORY: {result_category} article: {article}, price: {price}, ean: {ean}, description: {description}",
                save=True,
            )
            return None, None
        category_id = result_category["data"][0]["id_category"]
        category_name = result_category["data"][0]["name"]
        return category_id, category_name

    async def upload_single_product(
        self, item: dict, job_id: str | None = None
    ) -> bool:
        """
        Upload exactly 1 product.
        No batching, no asyncio.gather
        """
        return await self._create_product(item, job_id=job_id)

    async def _create_product(self, elem, job_id=None, controller=None):
        """
        Функция для создания продукта приходит elem: dict
        """
        if await is_cancelled(job_id):
            return False

        if not isinstance(elem, dict):
            await self._emit_ean_status(
                job_id,
                "error",
                None,
                self._build_item_payload(None),
                stage="validation",
                message="Invalid item payload type",
                detail=f"type={type(elem).__name__}",
            )
            return False

        item_payload = self._build_item_payload(elem)
        ean = elem.get("ean")

        log(f"[{ean}] Create product started")
        await self._emit_progress_event(
            job_id,
            "ean_started",
            payload={"status": "running", "ean": ean, "item": item_payload},
        )

        if not elem.get("ean"):
            log(f"ERROR WITH EAN: elem: {elem}", save=True)
            await self._emit_ean_status(
                job_id,
                "error",
                ean,
                item_payload,
                stage="validation",
                message="Missing EAN",
            )
            return False
        elif not elem.get("article"):
            log(f"ERROR WITH ARTICLE: elem: {elem}", save=True)
            await self._emit_ean_status(
                job_id,
                "error",
                ean,
                item_payload,
                stage="validation",
                message="Missing article",
            )
            return False
        elif elem.get("price", 0) < 30:
            log(f"ERROR WITH PRICE: elem: {elem}", save=True)
            await self._emit_ean_status(
                job_id,
                "error",
                ean,
                item_payload,
                stage="validation",
                message="Price below minimum",
                detail=str(elem.get("price")),
            )
            return False
        elif not elem.get("pic_main"):
            log(f"ERROR WITH PIC: elem: {elem}", save=True)
            await self._emit_ean_status(
                job_id,
                "error",
                ean,
                item_payload,
                stage="validation",
                message="Missing main picture",
            )
            return False

        article = elem["article"]
        size = elem["size"]
        color = elem["color"]
        material = elem["material"]
        price = int(elem["price"])
        total = (
            [elem["pic_main"]] + elem["pics"]
            if len(elem["pics"]) > 0 and elem["pics"][0]
            else [elem["pic_main"]]
        )
        fabric = elem["fabric"]

        if isinstance(material, list):
            material = ", ".join(material)

        if isinstance(color, list):
            color = ", ".join(color)

        delivery = 28

        if "cn" in fabric.lower():
            delivery = 40
        elif "tr" in fabric.lower() or "pl" in fabric.lower() or "it" in fabric.lower():
            delivery = 32

        ean = elem["ean"]

        await self._emit_stage(
            job_id,
            ean,
            item_payload,
            "generate_description_and_pics",
        )
        log(f"[{ean}] Generate description and pics tasks gather")
        description_task = generate_description(article, size, color, material)
        log(f"Image path <======={total}=======>")
        pics_task = process_pics(total)

        try:
            with log_time(f"[{ean}] generate desc + process img total"):
                description, pics = await asyncio.gather(description_task, pics_task)
        except Exception as e:
            await self._emit_ean_status(
                job_id,
                "error",
                ean,
                item_payload,
                stage="generate_description_and_pics",
                message="Failed to generate description or process pictures",
                detail=str(e),
            )
            return False

        height = elem["height"]
        length = elem["length"]
        width = elem["width"]

        # Получаем SSH клиент
        with log_time("Connection to ssh"):
            ssh_client = self._get_ssh_client()

        # Run independent stage calls in parallel to reduce per-EAN latency.
        seo_task = asyncio.create_task(
            generate_seo(article=article, size=size, color=color, material=material)
        )
        await self._emit_stage(job_id, ean, item_payload, "adapt_html_description")
        await self._emit_stage(job_id, ean, item_payload, "category_selector")
        adapt_task = asyncio.create_task(
            adapt_html_description(ean, description, ssh_client, controller)
        )
        category_task = asyncio.create_task(
            self._category_selector(article, price, ean, description)
        )

        adapt_result, category_result = await asyncio.gather(
            adapt_task, category_task, return_exceptions=True
        )
        if isinstance(adapt_result, Exception):
            await self._emit_stage(
                job_id,
                ean,
                item_payload,
                "adapt_html_description",
                status="warning",
                message="HTML description adaptation failed, using fallback",
                extra={"detail": str(adapt_result)},
            )
            log(
                f"HTML description adaptation failed for EAN {ean}: {adapt_result}",
                save=True,
            )
            new_webtag = description
        else:
            new_webtag = adapt_result

        if isinstance(category_result, Exception):
            if not seo_task.done():
                seo_task.cancel()
            await self._emit_ean_status(
                job_id,
                "error",
                ean,
                item_payload,
                stage="category_selector",
                message="Category selector failed",
                detail=str(category_result),
            )
            return False
        category_id, category_name = category_result

        log(f"CATEGORIES: {category_id}, NAME: {category_name}")

        if category_id is None:
            if not seo_task.done():
                seo_task.cancel()
            log(f"ERROR WITH CATEGORY ID IS NONE: EAN: {ean}", save=True)
            await self._emit_ean_status(
                job_id,
                "error",
                ean,
                item_payload,
                stage="category_selector",
                message="Category selector returned empty category",
            )
            return False

        try:
            seo_list = await seo_task
        except Exception as e:
            log(f"generate_seo failed for EAN {ean}: {e}", save=True)
            seo_list = []

        attributes = {
            "title": [article],
            "description": [new_webtag],
            "ean": [ean],
            "picture": pics,
            "category": [category_name],
            "category_detail": {
                "id": category_id,
                "title": category_name,
                "name": category_name,
            },
            "short_description": seo_list,
        }

        optional_fields = {
            "colour": color,
            "height": height,
            "length": length,
            "width": width,
            "material": (
                material if material not in ["Stoff", "Textil"] else "Synthetic"
            ),
            "material_composition": "No information required",
            "abnehmbarer_bezug": "No",
            "parts_of_animal_origin": "Yes" if material == "Leder" else "No",
        }

        for key, value in optional_fields.items():
            if value:
                attributes[key] = [value]

        json_body = {"ean": [ean], "attributes": attributes}

        if self.version == "jv":
            json_body["attributes"]["manufacturer"] = JV_MANUFACTURER
            json_body["attributes"]["product_safety_contact"] = JV_CONTACT_DATA
        else:
            json_body["attributes"]["manufacturer"] = XL_MANUFACTURER
            json_body["attributes"]["product_safety_contact"] = XL_CONTACT_DATA

        url = f"{self.base_api_url}/product-data?locale=de-DE"

        await self._emit_stage(job_id, ean, item_payload, "create_product_body")
        try:
            log(f"Sending request with body: {json_body}")
            with log_time(f"API request with method PUT on url {url}"):
                result = await self._universal_request("PUT", url, json_body)
        except Exception as e:
            await self._emit_ean_status(
                job_id,
                "error",
                ean,
                item_payload,
                stage="create_product_body",
                message="Create product body request failed",
                detail=str(e),
            )
            return False

        if not isinstance(result, dict):
            await self._emit_ean_status(
                job_id,
                "error",
                ean,
                item_payload,
                stage="create_product_body",
                message="Unexpected create product response type",
                detail=f"type={type(result).__name__}",
            )
            return False
        log(f"[{ean}] The result of API request: {result}")

        if result.get("data") == "Content created or replaced":
            try:
                await self._emit_stage(job_id, ean, item_payload, "fetch_unit_id")
                with log_time("Unit fetch request"):
                    unit_ids = await self._fetch_unit_id_by_ean(ean)
            except Exception as e:
                await self._emit_ean_status(
                    job_id,
                    "error",
                    ean,
                    item_payload,
                    stage="fetch_unit_id",
                    message="Failed to fetch unit_id",
                    detail=str(e),
                )
                return False

            if unit_ids:
                await self._emit_stage(job_id, ean, item_payload, "update_price")

                with log_time(f"[{ean}] update price"):
                    update_result = await self._update_price_by_unit_id(
                        ean, price, unit_ids
                    )

                missing_storefronts = [
                    storefront
                    for storefront in storefronts
                    if storefront not in unit_ids
                ]
                add_result = True
                if missing_storefronts:
                    await self._emit_stage(job_id, ean, item_payload, "add_unit")
                    add_result = await self._add_unit_id(
                        ean, price, delivery, target_storefronts=missing_storefronts
                    )

                overall_result = update_result and add_result
                status_stage = "add_unit" if missing_storefronts else "update_price"
                if overall_result:
                    message = (
                        "Price updated"
                        if not missing_storefronts
                        else "Price updated, missing units created"
                    )
                    await self._emit_ean_status(
                        job_id,
                        "success",
                        ean,
                        item_payload,
                        stage=status_stage,
                        message=message,
                    )
                else:
                    if not update_result and not add_result:
                        message = "Price update and missing unit creation failed"
                    elif not update_result:
                        message = (
                            "Price update failed; missing units created"
                            if add_result
                            else "Price update failed"
                        )
                    else:
                        message = "Missing unit creation failed"
                    await self._emit_ean_status(
                        job_id,
                        "error",
                        ean,
                        item_payload,
                        stage=status_stage,
                        message=message,
                    )
                return overall_result
            else:
                await self._emit_stage(job_id, ean, item_payload, "add_unit")
                result = await self._add_unit_id(ean, price, delivery)
                if result:
                    await self._emit_ean_status(
                        job_id,
                        "success",
                        ean,
                        item_payload,
                        stage="add_unit",
                        message="Product created",
                    )
                else:
                    await self._emit_ean_status(
                        job_id,
                        "error",
                        ean,
                        item_payload,
                        stage="add_unit",
                        message="Failed to create product",
                    )
                return result
        else:
            log(f"ERROR WITH CREATING PRODUCT BODY: {result} elem: {elem}", save=True)
            await self._emit_ean_status(
                job_id,
                "error",
                ean,
                item_payload,
                stage="create_product_body",
                message="Failed to create product body",
                detail=json.dumps(result, ensure_ascii=False),
            )
            return False

    async def delete_all_products(self, eans, job_id: str | None = None):
        """
        Удаление товаров по их EAN со всех сайтов в kaufland
        """
        logs_dir = os.path.join(settings.MEDIA_ROOT, "logs")
        logs_file_path = os.path.join(logs_dir, "delete_products_logs.csv")

        # Проверка существования файла
        if os.path.exists(logs_file_path):
            os.remove(logs_file_path)

        clean_eans = [ean for ean in eans if ean and ean != "nan"]
        total = len(clean_eans)
        if job_id:
            await clear_cancel(job_id)
            await self._send_task_progress(
                job_id,
                "delete",
                "job_started",
                payload={"total": total, "controller": self.version},
            )

        if not clean_eans:
            return True

        processed = 0
        result_list = []
        failed_eans = []
        success_count = 0
        error_count = 0
        last_progress_emit_at = None
        step = 10
        if job_id:
            await register_running_job(job_id)
        try:
            for elem in range(0, len(clean_eans), step):
                if await is_cancelled(job_id):
                    if job_id:
                        await self._send_task_progress(
                            job_id,
                            "delete",
                            "job_failed",
                            payload={
                                "total": total,
                                "processed": processed,
                                "success": success_count,
                                "error": error_count,
                                "failed_eans": failed_eans,
                            },
                            info="stopped",
                        )
                    return False
                batch_eans = clean_eans[elem : elem + step]
                tasks = [
                    self._delete_product_by_unit_id(str(int(float(ean))), job_id=job_id)
                    for ean in batch_eans
                ]
                batch_result = await asyncio.gather(*tasks)
                for ean, ok in zip(batch_eans, batch_result):
                    processed += 1
                    result_list.append(ok)
                    normalized_ean = str(int(float(ean)))
                    if not ok:
                        error_count += 1
                        failed_eans.append(normalized_ean)
                    else:
                        success_count += 1
                    if job_id:
                        if self._should_emit_progress(
                            processed=processed,
                            total=total,
                            last_emit_at=last_progress_emit_at,
                        ):
                            await self._send_task_progress(
                                job_id,
                                "delete",
                                "job_progress",
                                payload={
                                    "total": total,
                                    "processed": processed,
                                    "success": success_count,
                                    "error": error_count,
                                    "ean": normalized_ean,
                                    "status": "success" if ok else "failed",
                                },
                            )
                            last_progress_emit_at = time.monotonic()
        except asyncio.CancelledError:
            if job_id:
                await self._send_task_progress(
                    job_id,
                    "delete",
                    "job_failed",
                    payload={
                        "total": total,
                        "processed": processed,
                        "success": success_count,
                        "error": error_count,
                        "failed_eans": failed_eans,
                    },
                    info="stopped",
                )
            return False
        finally:
            if job_id:
                await unregister_running_job(job_id)

        status_result = all(result_list)
        if job_id:
            await self._send_task_progress(
                job_id,
                "delete",
                "job_completed",
                payload={
                    "total": total,
                    "processed": processed,
                    "success": success_count,
                    "failed": error_count,
                    "failed_eans": failed_eans,
                },
                info="success" if status_result else "partial_or_failed",
            )
        return status_result

    async def update_price(self, eans_and_prices):
        """
        Функция для обновления цен по EAN с уже указанным price
        """
        logs_dir = os.path.join(settings.MEDIA_ROOT, "logs")
        logs_file_path = os.path.join(logs_dir, "update_price_logs.csv")

        # Проверка существования файла
        if os.path.exists(logs_file_path):
            os.remove(logs_file_path)

        tasks = [
            self._update_price_by_unit_id(str(int(float(ean))), price)
            for ean, price in eans_and_prices.items()
            if ean and ean != "nan"
        ]
        status_result = await self.status_processing(tasks)
        return status_result

    async def products_checker(self, eans, job_id: str | None = None):
        """
        Чекер продуктов выводит их ean, title, price
        """
        results = []
        clean_eans = [ean for ean in eans if ean and ean != "nan"]
        total = len(clean_eans)
        if job_id:
            await clear_cancel(job_id)
            await self._send_task_progress(
                job_id,
                "checker",
                "job_started",
                payload={"total": total, "controller": self.version},
            )
        if not clean_eans:
            if job_id:
                await self._send_task_progress(
                    job_id,
                    "checker",
                    "job_completed",
                    payload={
                        "total": total,
                        "processed": 0,
                        "found": 0,
                        "not_found": 0,
                        "results": [],
                    },
                )
            return results

        processed = 0
        found_count = 0
        not_found_count = 0
        last_progress_emit_at = None
        if job_id:
            await register_running_job(job_id)
        try:
            for elem in range(0, len(clean_eans), 10):
                if await is_cancelled(job_id):
                    if job_id:
                        await self._send_task_progress(
                            job_id,
                            "checker",
                            "job_failed",
                            payload={
                                "total": total,
                                "processed": processed,
                                "success": found_count,
                                "error": 0,
                                "not_found": not_found_count,
                                "results": results,
                            },
                            info="stopped",
                        )
                    return results
                batch_eans = clean_eans[elem : elem + 10]
                normalized_batch_eans = [str(int(float(ean))) for ean in batch_eans]
                tasks = [
                    self._check_product_by_unit_id(normalized_ean, job_id=job_id)
                    for normalized_ean in normalized_batch_eans
                ]
                result = await asyncio.gather(*tasks, return_exceptions=True)
                for normalized_ean, item in zip(normalized_batch_eans, result):
                    if isinstance(item, Exception):
                        log(
                            f"products_checker failed and stopped ean={normalized_ean} error={item}",
                            save=True,
                        )
                        if job_id:
                            await self._send_task_progress(
                                job_id,
                                "checker",
                                "job_failed",
                                payload={
                                    "total": total,
                                    "processed": processed,
                                    "failed_ean": normalized_ean,
                                    "results": results,
                                },
                                info=str(item),
                            )
                        raise RuntimeError(
                            f"products_checker failed for ean={normalized_ean}: {item}"
                        ) from item
                    results.append(item)
                    if item.get("found"):
                        found_count += 1
                    else:
                        not_found_count += 1
                    processed += 1
                    if job_id:
                        if self._should_emit_progress(
                            processed=processed,
                            total=total,
                            last_emit_at=last_progress_emit_at,
                        ):
                            await self._send_task_progress(
                                job_id,
                                "checker",
                                "job_progress",
                                payload={
                                    "total": total,
                                    "processed": processed,
                                    "success": processed,
                                    "error": 0,
                                    "ean": normalized_ean,
                                },
                            )
                            last_progress_emit_at = time.monotonic()
        except asyncio.CancelledError:
            if job_id:
                await self._send_task_progress(
                    job_id,
                    "checker",
                    "job_failed",
                    payload={
                        "total": total,
                        "processed": processed,
                        "success": found_count,
                        "error": 0,
                        "not_found": not_found_count,
                        "results": results,
                    },
                    info="stopped",
                )
            return results
        finally:
            if job_id:
                await unregister_running_job(job_id)
        if job_id:
            await self._send_task_progress(
                job_id,
                "checker",
                "job_completed",
                payload={
                    "total": total,
                    "processed": processed,
                    "found": found_count,
                    "not_found": not_found_count,
                    "results": results,
                },
            )
        return results

    async def upload_via_json(
        self, data: list[dict], job_id: str | None = None
    ) -> bool | None:
        """
        Функция для загрузки товаров на Kaufland через JSON
        Arguments:
            data (list[dict]): Список товаров в формате словаря
        Returns:
            optional[bool]:
                - True: все товары успешно загружены
                - False: загружены не все товары
                - None: все товары не загружены
        """
        # Компилируем регулярное выражение для поиска ключевых слов
        pattern = re.compile(r"(delet\w*|remove\w*|l[oö]sch\w*)", re.IGNORECASE)

        # Сохраняем исходную длину данных
        original_len = len(data)

        # Фильтруем данные, исключая элементы, содержащие ключевые слова
        safe_data = [elem for elem in data if isinstance(elem, dict)]
        removed_invalid_items = len(data) - len(safe_data)
        data = [
            elem
            for elem in safe_data
            if not pattern.search(str(elem.get("article", "")))
        ]

        # Keep only unique EANs from the start.
        unique_data: list[dict] = []
        seen_eans: set[str] = set()
        removed_duplicates = 0
        for item in data:
            ean_value = str(item.get("ean") or "").strip()
            if not ean_value:
                unique_data.append(item)
                continue
            if ean_value in seen_eans:
                removed_duplicates += 1
                continue
            seen_eans.add(ean_value)
            unique_data.append(item)
        data = unique_data

        result_list = []
        concurrency = self.upload_batch_size

        skipped_count = original_len - len(data)

        # Если были удалены элементы, фиксируем это в логах и прогрессе.
        if removed_invalid_items:
            log(
                f"upload skipped invalid items count={removed_invalid_items}", save=True
            )
        if removed_duplicates:
            log(f"upload skipped duplicate eans count={removed_duplicates}", save=True)

        if not job_id:
            job_id = uuid4().hex
        await clear_cancel(job_id)

        total = len(data)
        await self._emit_progress_event(
            job_id,
            "job_started",
            payload={
                "total": total,
                "controller": self.version,
                "skipped": skipped_count,
                "skipped_invalid": removed_invalid_items,
                "skipped_duplicates": removed_duplicates,
            },
        )

        success_count = 0
        error_count = 0
        processed_count = 0
        failed_eans = []

        last_progress_emit_at = None
        work_queue: asyncio.Queue = asyncio.Queue()
        done_queue: asyncio.Queue = asyncio.Queue()
        for item in data:
            await work_queue.put(item)
        worker_count = min(concurrency, total) if total > 0 else 0
        for _ in range(worker_count):
            await work_queue.put(None)

        async def run_upload_worker():
            while True:
                item = await work_queue.get()
                if item is None:
                    work_queue.task_done()
                    return

                ok = False
                ean = None
                try:
                    if await is_cancelled(job_id):
                        ok = False
                    else:
                        if isinstance(item, dict):
                            raw_ean = item.get("ean")
                            ean = str(raw_ean).strip() if raw_ean is not None else None
                        lock_token = await acquire_ean_lock(
                            ean, owner=f"{job_id}:{self.version}"
                        )
                        if ean and not lock_token:
                            await self._emit_ean_status(
                                job_id,
                                "error",
                                ean,
                                self._build_item_payload(item),
                                stage="acquire_ean_lock",
                                message="EAN is already being uploaded by another task",
                            )
                            log(
                                f"upload skipped locked ean={ean} job_id={job_id}",
                                save=True,
                            )
                            ok = False
                        else:
                            try:
                                ok = bool(
                                    await self._create_product(
                                        item, job_id, self.version
                                    )
                                )
                            finally:
                                await release_ean_lock(ean, lock_token)
                except Exception as e:
                    log(
                        f"upload unexpected error ean={ean} error={e}",
                        save=True,
                    )
                    ok = False
                finally:
                    await done_queue.put((item, ok))
                    work_queue.task_done()

        if job_id:
            await register_running_job(job_id)
        workers = [
            asyncio.create_task(run_upload_worker()) for _ in range(worker_count)
        ]
        try:
            while processed_count < total:
                if await is_cancelled(job_id):
                    for worker in workers:
                        worker.cancel()
                    if workers:
                        await asyncio.gather(*workers, return_exceptions=True)
                    await self._emit_progress_event(
                        job_id,
                        "job_failed",
                        payload={
                            "total": total,
                            "processed": processed_count,
                            "success": success_count,
                            "error": error_count,
                            "failed_eans": failed_eans,
                        },
                        info="stopped",
                    )
                    return False
                try:
                    item, ok = await asyncio.wait_for(done_queue.get(), timeout=0.25)
                except asyncio.TimeoutError:
                    continue
                result_list.append(ok)
                processed_count += 1
                current_ean = item.get("ean") if isinstance(item, dict) else None
                if ok:
                    success_count += 1
                else:
                    error_count += 1
                    if current_ean is not None:
                        failed_eans.append(str(current_ean))
                if self._should_emit_progress(
                    processed=processed_count,
                    total=total,
                    last_emit_at=last_progress_emit_at,
                ):
                    await self._emit_progress_event(
                        job_id,
                        "job_progress",
                        payload={
                            "total": total,
                            "processed": processed_count,
                            "success": success_count,
                            "error": error_count,
                            "ean": current_ean,
                        },
                    )
                    last_progress_emit_at = time.monotonic()
            if workers:
                await asyncio.gather(*workers, return_exceptions=True)
        except asyncio.CancelledError:
            for worker in workers:
                worker.cancel()
            if workers:
                await asyncio.gather(*workers, return_exceptions=True)
            await self._emit_progress_event(
                job_id,
                "job_failed",
                payload={
                    "total": total,
                    "processed": processed_count,
                    "success": success_count,
                    "error": error_count,
                    "failed_eans": failed_eans,
                },
                info="stopped",
            )
            return False
        finally:
            if job_id:
                await unregister_running_job(job_id)
        if all(result_list):  # Все успешно
            await self._emit_progress_event(
                job_id,
                "job_completed",
                payload={
                    "status": "success",
                    "total": total,
                    "processed": processed_count,
                    "success": success_count,
                    "error": error_count,
                    "skipped": skipped_count,
                    "skipped_invalid": removed_invalid_items,
                    "skipped_duplicates": removed_duplicates,
                    "failed_eans": failed_eans,
                },
            )
            return True
        elif any(result_list) and not all(result_list):  # Частично успешно
            await self._emit_progress_event(
                job_id,
                "job_completed",
                payload={
                    "status": "partial",
                    "total": total,
                    "processed": processed_count,
                    "success": success_count,
                    "error": error_count,
                    "skipped": skipped_count,
                    "skipped_invalid": removed_invalid_items,
                    "skipped_duplicates": removed_duplicates,
                    "failed_eans": failed_eans,
                },
            )
            return False

        elif not any(result_list):  # Все неуспешно
            await self._emit_progress_event(
                job_id,
                "job_completed",
                payload={
                    "status": "failed",
                    "total": total,
                    "processed": processed_count,
                    "success": success_count,
                    "error": error_count,
                    "skipped": skipped_count,
                    "skipped_invalid": removed_invalid_items,
                    "skipped_duplicates": removed_duplicates,
                    "failed_eans": failed_eans,
                },
            )
            return None

    async def get_product_by_ean(self, ean: str):
        """
        Получить информацию о товаре по его EAN в читаемом формате:
        один объект на storefront с объединенным data:
        main product data + embedded entities.
        """

        base_url = f"{self.base_api_url}/product-data/{ean}?locale=de-DE"
        additional_url = (
            f"{self.base_api_url}/products/ean/{ean}?storefront=de&embedded=units"
        )

        main_data = None
        additional_data = None

        main_data = await self._universal_request("GET", base_url)
        additional_data = await self._universal_request("GET", additional_url)

        main_attributes = main_data.get("data").get("attributes")

        units = additional_data.get("data").get("units")
        prices = map(lambda unit: unit.get("price"), units)

        response_data = {}

        for key, value in main_attributes.items():
            if not value:
                response_data[key] = [None]
            elif isinstance(value, list):
                response_data[key] = value
            else:
                response_data[key] = [value]
        response_data["price"] = prices

        return {"response_data": response_data}


async def main():
    async with aiohttp.ClientSession() as session:
        cnt = KauflandController(session, version="jv")
        ean_dict = {
            "4067282748224": 4999,
            "4067282749382": 4999,
            "4067282736344": 4999,
            "4067282749030": 4999,
            "4067282748941": 4999,
            "4067282749214": 4999,
            "4067282736887": 4999,
            "4067282749290": 4999,
            "4067282749122": 4999,
            "4067282748316": 4999,
            "4067282736795": 4999,
            "4067282748132": 4999,
            "4067282737150": 4999,
            "4067282736078": 4999,
            "4067282736160": 4999,
            "4067282748859": 4999,
            "4067282737426": 4999,
            "4067282740051": 4999,
            "4067282748767": 4999,
            "4067282740310": 4999,
            "4067282735613": 4999,
            "4067282731301": 4999,
            "4067282740228": 4999,
            "4067282736528": 4999,
            "4067282737068": 4999,
            "4067282748675": 4999,
            "4067282736610": 4999,
            "4067282736252": 4999,
            "4067282735354": 4999,
            "4067282737242": 4999,
            "4067282737334": 4999,
            "4067282736702": 4999,
            "4067282735897": 4999,
            "4062292279850": 4999,
            "4067282735262": 4999,
            "4062292723353": 4999,
            "4062292419706": 4999,
            "4067282498785": 4999,
            "4067282497658": 4999,
            "4067282740150": 4999,
            "4067282736009": 4999,
            "4067282736993": 4999,
        }
        settings.configure()

        # for ean, price in ean_dict.items():
        #     result = await cnt._add_unit_id(ean, price, 28)
        #     log(result)
        # https://sellerapi.kaufland.com/v2/units/387978729501?storefront=de&embedded=battery_participation


if __name__ == "__main__":
    asyncio.run(main())
