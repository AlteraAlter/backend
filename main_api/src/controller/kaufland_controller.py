import os
import re
import math
import time
import hmac
import json
import random
import asyncio
from uuid import uuid4
import certifi
import aiohttp
import hashlib
from datetime import datetime
from aiohttp import ClientError
from django.conf import settings
from channels.layers import get_channel_layer
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
from main_api.src.ssh_client import SSHFileClient
from main_api.src.extracter import adapt_html_description
from main_api.src.servises.pic_pipline import process_pics
from main_api.src.utils.timer import log_time
from main_api.src.gpt.gpt_helper import generate_description, generate_seo


class KauflandController:
    """
    Класс для взаимодействия с кауфлендом
    """

    def __init__(self, session, version):
        self.limiter = AsyncLimiter(50, time_period=1)  # 100 req/sec is Limit
        self.session = session
        self.version = version
        self.retries = 3
        self.backoff = 2
        self.base_api_url = "https://sellerapi.kaufland.com/v2"
        self._ssh_client = None  # Коннекшн к ншашему серверу

        # Мини кэшируемая система
        self._ean_cache = {
            "unit_ids": {},
            "product_ids": {},
            "main_data": {},
        }

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
    async def _universal_request(self, method, url, body=None, params=None):
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
            try:
                async with self.limiter:
                    if method == "GET":
                        async with self.session.get(
                            url=url, headers=headers, params=params, ssl=ssl_cert
                        ) as response:
                            # response.raise_for_status()
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
            except (asyncio.TimeoutError, ClientError) as e:
                log(
                    f"[{method}] Попытка {attempt}/{self.retries} не удалась ERROR: {e} "
                    f"payload: {json.dumps(body, indent=2)}\nheaders: {json.dumps(headers, indent=2)}",
                    save=True,
                )
                if attempt == self.retries:
                    raise
                await asyncio.sleep(
                    self.backoff * attempt * (random.randint(1, 10) / 10)
                )

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

        final_res = {}
        for storefront in storefronts:
            url = f"{self.base_api_url}/products/ean/{ean}?storefront={storefront}&embedded=units"
            result = await self._universal_request(method="GET", url=url)
            unit_id = result.get("data", {}).get("units", [{}])[0].get("id_unit", None)
            if unit_id:
                final_res[storefront] = unit_id

        self._ean_cache["unit_ids"][ean] = final_res
        return final_res

    async def _fetch_product_id_by_ean(self, ean):
        """
        Функция которая собирает product_id
        о продукте по его EAN со всех стран
        """
        if ean in self._ean_cache["product_ids"]:
            return self._ean_cache["product_ids"][ean]

        final_res = {}
        for storefront in storefronts:
            url = f"{self.base_api_url}/products/ean/{ean}?storefront={storefront}&embedded=units"
            result = await self._universal_request(method="GET", url=url)
            log(f"Подтянули данные по product_id: {result}")
            product_id = result.get("data", {}).get("id_product", "")
            if product_id:
                final_res[storefront] = product_id
        self._ean_cache["product_ids"][ean] = final_res
        return final_res

    async def _add_unit_id(self, ean, price, delivery):
        """
        Функция для создания внутренного id продукта
        для Kaufland
        """
        bool_list = []

        for storefront in storefronts:
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

            result = await self._universal_request("POST", url, body=body)

            if result.get("data", {}).get("status", "") == "AVAILABLE":
                log(f"Unit был создан для EAN: {ean} в стране: {storefront}", save=True)
                bool_list.append(True)
            else:
                log(f"Не получилось создать Unit: {result}", save=True)
                log(
                    f"Вот такие данные: body:{json.dumps(body, indent=2)}\nstorefront:{storefront}",
                    save=True,
                )
                bool_list.append(False)
        if all(bool_list):
            log(f"Продукт {ean} для всех стран был создан")
            return True
        return False

    async def _fetch_old_price_by_unit_id(self, units_id_dict: dict[str, str]):
        """
        Функция которая собирает старую цену
        о продукте по его unit_id
        """
        final_res = {}
        for storefront, unit_id in units_id_dict.items():
            url = f"{self.base_api_url}/units/{unit_id}?storefront={storefront}&embedded=products"
            result = await self._universal_request(method="GET", url=url)
            if result:
                price = result.get("data", {}).get("listing_price", None)
                final_res[unit_id] = price
        return final_res

    async def _fetch_main_data_by_ean(self, ean):
        """
        Функция которая собирает unit_id, title, price
        """

        if ean in self._ean_cache["main_data"]:
            return self._ean_cache["main_data"][ean]

        final_res = []
        for storefront in storefronts:
            url = f"{self.base_api_url}/products/ean/{ean}?storefront={storefront}&embedded=units"
            result = await self._universal_request(method="GET", url=url)
            id_unit = result.get("data", {}).get("units", [{}])[0].get("id_unit", None)
            if id_unit:
                title = result["data"]["title"]
                price = float(result["data"]["units"][0]["price"]) / 100
                storefront = result["data"]["storefront"]
                final_res.append(
                    {
                        "ean": ean,
                        "title": title,
                        "price": price,
                        "storefront": storefront,
                    }
                )
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
        channel_layer = get_channel_layer()

        log(
            f"WS SEND job_id={job_id} event={event} payload={payload} info={info}",
            save=True,
        )
        await channel_layer.group_send(
            f"{job_id}_upload",
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

    def _build_item_payload(self, elem: dict) -> dict:
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

    async def _update_price_by_unit_id(self, ean, price):
        """
        Обновление цены по его unit_id
        """
        channel_layer = get_channel_layer()
        log(f"EAN: {ean}")
        final_res = await self._fetch_unit_id_by_ean(ean)

        if final_res:
            old_price_dict = await self._fetch_old_price_by_unit_id(final_res)
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
                        "price_updates",  # Группа
                        {
                            "type": "price_update",
                            "ean": ean,
                            "new_price": total_price / 100,  # Для удобства менеджеров
                            "old_price": old_price_dict[unit_id]
                            / 100,  # Для удобства менеджеров
                            "storefront": storefront,
                            "timestamp": datetime.now().isoformat(),
                            "result": message,
                        },
                    )
                    log(
                        f"Обновили цену price: {price} EAN:{ean} unit_id:{unit_id} country: {storefront}",
                        save=True,
                    )
                    bool_list.append(True)
                elif message == "not found":
                    await channel_layer.group_send(
                        "price_updates",  # Группа
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
                    log(
                        f"Обновили цену price: {price} EAN:{ean} unit_id:{unit_id} country: {storefront}",
                        save=True,
                    )
                    bool_list.append(True)
                else:
                    await channel_layer.group_send(
                        "price_updates",  # Группа
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
                    log(
                        f"Что-то пошло не так не обновили цену {price} EAN:{ean} unit_id:{unit_id} country: {storefront}",
                        save=True,
                    )
                    bool_list.append(False)
            if all(bool_list):
                return True
            else:
                return False
        await channel_layer.group_send(
            "price_updates",  # Группа
            {
                "type": "price_update",
                "ean": ean,
                "new_price": 0,
                "old_price": 0,
                "storefront": "Все базы",
                "timestamp": datetime.now().isoformat(),
                "result": {"message": "Товара не существует"},
            },
        )
        return True

    async def _delete_product_by_unit_id(self, ean: str) -> bool:
        """
        Функция которая удаляет товары по их
        unit_id
        """
        channel_layer = get_channel_layer()
        logs_dir = os.path.join(settings.MEDIA_ROOT, "logs")
        logs_file_path = os.path.join(logs_dir, "delete_products_logs.csv")
        os.makedirs(logs_dir, exist_ok=True)

        final_res = await self._fetch_unit_id_by_ean(ean)
        log(f"Пришел final_res для удаления ean: {ean}", save=True)
        if final_res:
            log(f"ean: {ean} | final_res: {final_res}", save=True)
            bool_list = []
            for storefront, unit_id in final_res.items():
                url = f"{self.base_api_url}/units/{unit_id}?storefront={storefront}"
                result = await self._universal_request(method="DELETE", url=url)
                if result:
                    bool_list.append(True)
                    log(
                        f"Был удален товар из Kaufland {self.version} EAN: {ean} Страна: {storefront}",
                        save=True,
                    )
                    with open(logs_file_path, "a", encoding="utf-8") as file:
                        file.write(
                            f"\nБыл удален товар из Kaufland {self.version} EAN: {ean} "
                            f"Страна: {storefront}\n"
                        )
                else:
                    bool_list.append(False)
                    log(
                        f"Товар не был удален из Kaufland {self.version} EAN: {ean} Страна: {storefront}",
                        save=True,
                    )
                    with open(logs_file_path, "a", encoding="utf-8") as file:
                        file.write(
                            f"\nТовар не был удален из Kaufland {self.version} EAN: {ean} "
                            f"Страна: {storefront}\n"
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

            return all(bool_list)

        log(f"Нет Final res ean: {ean}", save=True)

        await channel_layer.group_send(
            "delete_group",
            {
                "type": "delete_message",
                "message": {"info": "Нету unit-ids"},
                "controller": self.version,
                "ean": ean,
                "storefront": "Все базы",
            },
        )

        log(f"Не существует такого EAN: {ean}", save=True)
        with open(logs_file_path, "a", encoding="utf-8") as file:
            file.write(f"\nНе существует такого EAN: {ean}\n")
        return True

    async def realtime_check(self, ean: str) -> dict:
        """
        Fast EAN existance check (no heavy parsing)
        """
        if ean in self._ean_cache["units_id"]:
            return {
                "ean": ean,
                "exists": bool(self._ean_cache["units_id"][ean]),
                "source": "cache",
            }
        for storefront in storefronts:
            url = f"{self.base_api_url}/products/ean/{ean}?storefront={storefront}"
            res = await self._universal_request("GET", url)
            if res.get("data"):
                self._ean_cache["unit_id"][ean] = {storefront: True}
                return {"ean": ean, "exists": True, "storefront": storefront}

        self._ean_cache["unit_id"][ean] = {}
        return {"ean": ean, "exists": False}

    async def _check_product_by_unit_id(self, ean):
        """
        Выводит чек 1 продукта по unit_id
        """
        channel_layer = get_channel_layer()
        final_res = await self._fetch_main_data_by_ean(ean)
        await channel_layer.group_send(
            "realtime_group",
            {
                "type": "realtime_message",
                "message": {
                    "controller": self.version,
                    "ean": ean,
                    "final_res": final_res,
                },
                "controller": self.version,
                "ean": ean,
            },
        )
        if final_res:
            log(f"Пришел Res: {final_res}")
            return final_res
        log(f"Пришел Res: {final_res}")
        return {"ean": ean, "title": None, "price": None, "storefront": None}

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

    async def upload_single_product(self, item: dict, job_id: str | None = None) -> bool:
        """
        Upload exactly 1 product.
        No batching, no asyncio.gather
        """
        return await self._create_product(item, job_id=job_id)

    async def _create_product(self, elem, job_id=None):
        """
        Функция для создания продукта приходит elem: dict
        """
        item_payload = self._build_item_payload(elem)
        ean = elem.get("ean")

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

        log(f"Создаем продукт с EAN: {elem['ean']}", save=True)

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

        description_task = generate_description(article, size, color, material)
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

        # Получаем HTML-описание из extracter (оригинал из файла), затем добавляем в атрибуты
        try:
            await self._emit_stage(job_id, ean, item_payload, "adapt_html_description")
            new_webtag = await adapt_html_description(ean, description, ssh_client)
        except Exception as e:
            await self._emit_stage(
                job_id,
                ean,
                item_payload,
                "adapt_html_description",
                status="warning",
                message="HTML description adaptation failed, using fallback",
                extra={"detail": str(e)},
            )
            log(f"HTML description adaptation failed for EAN {ean}: {e}", save=True)
            new_webtag = description
        await self._emit_stage(job_id, ean, item_payload, "category_selector")
        try:
            category_id, category_name = await self._category_selector(
                article, price, ean, description
            )
        except Exception as e:
            await self._emit_ean_status(
                job_id,
                "error",
                ean,
                item_payload,
                stage="category_selector",
                message="Category selector failed",
                detail=str(e),
            )
            return False
        if category_id is None:
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

        seo_list = await generate_seo(
            article=article, size=size, color=color, material=material
        )

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
            "material": material,
            "material_composition": "No information required",
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

        if result.get("data") == "Content created or replaced":
            log(f"Тело продукта создалось с EAN: {ean}", save=True)

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
                log(
                    f"Продукт c таким EAN ({ean}) уже существует, обновляем цену",
                    save=True,
                )

                await self._emit_stage(job_id, ean, item_payload, "update_price")
                with log_time(f"[{ean}] update price"):
                    result = await self._update_price_by_unit_id(ean, price)
                log(
                    f"Result of updating price for EAN: {ean} result: {result}",
                    save=True,
                )

                if result:
                    await self._emit_ean_status(
                        job_id,
                        "success",
                        ean,
                        item_payload,
                        stage="update_price",
                        message="Price updated",
                    )
                else:
                    await self._emit_ean_status(
                        job_id,
                        "error",
                        ean,
                        item_payload,
                        stage="update_price",
                        message="Price update failed",
                    )
                return result
            else:
                log(f"Product with EAN ({ean}) not found, creating new unit", save=True)
                await self._emit_stage(job_id, ean, item_payload, "add_unit")
                result = await self._add_unit_id(ean, price, delivery)
                log(
                    f"Result of creating product with EAN: {ean} result: {result}",
                    save=True,
                )
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

    async def delete_all_products(self, eans):
        """
        Удаление товаров по их EAN со всех сайтов в kaufland
        """
        logs_dir = os.path.join(settings.MEDIA_ROOT, "logs")
        logs_file_path = os.path.join(logs_dir, "delete_products_logs.csv")

        # Проверка существования файла
        if os.path.exists(logs_file_path):
            os.remove(logs_file_path)
            log(f"Файл {logs_file_path} успешно удалён")
        else:
            log(f"Файл {logs_file_path} не существует")

        tasks = [
            self._delete_product_by_unit_id(str(int(float(ean))))
            for ean in eans
            if ean and ean != "nan"
        ]
        status_result = await self.status_processing(tasks)
        return status_result

    async def update_price(self, eans_and_prices):
        """
        Функция для обновления цен по EAN с уже указанным price
        """
        log(f"Вот такой eans_and_prices: {eans_and_prices}", save=True)
        logs_dir = os.path.join(settings.MEDIA_ROOT, "logs")
        logs_file_path = os.path.join(logs_dir, "update_price_logs.csv")

        # Проверка существования файла
        if os.path.exists(logs_file_path):
            os.remove(logs_file_path)
            log(f"Файл {logs_file_path} успешно удалён")
        else:
            log(f"Файл {logs_file_path} не существует")

        tasks = [
            self._update_price_by_unit_id(str(int(float(ean))), price)
            for ean, price in eans_and_prices.items()
            if ean and ean != "nan"
        ]
        status_result = await self.status_processing(tasks)
        return status_result

    async def products_checker(self, eans):
        """
        Чекер продуктов выводит их ean, title, price
        """
        final_result = []
        tasks = [
            self._check_product_by_unit_id(str(int(float(ean))))
            for ean in eans
            if ean and ean != "nan"
        ]
        for elem in range(0, len(tasks), 10):
            new_tasks = tasks[elem : elem + 10]
            result = await asyncio.gather(*new_tasks)
            for elem in result:
                final_result.extend(elem)
        return final_result

    async def upload_via_json(self, data: list[dict], job_id: str | None = None) -> bool | None:
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
        data = [elem for elem in data if not pattern.search(elem["article"])]

        result_list = []
        step = 3

        # Если были удалены элементы, фиксируем это
        if len(data) < original_len:
            result_list.append(False)

        if not job_id:
            job_id = uuid4().hex

        total = len(data)
        await self._emit_progress_event(
            job_id,
            "job_started",
            payload={"total": total, "controller": self.version},
        )

        success_count = 0
        error_count = 0
        processed_count = 0

        tasks = [self._create_product(elem, job_id) for elem in data]
        for elem in range(0, len(data), step):
            batch_tasks = tasks[elem : elem + step]
            batch_items = data[elem : elem + step]
            result = await asyncio.gather(*batch_tasks)
            if all(result):
                result_list.append(True)
            else:
                result_list.append(False)
            for item, ok in zip(batch_items, result):
                processed_count += 1
                if ok:
                    success_count += 1
                else:
                    error_count += 1
                await self._emit_progress_event(
                    job_id,
                    "job_progress",
                    payload={
                        "total": total,
                        "processed": processed_count,
                        "success": success_count,
                        "error": error_count,
                        "ean": item.get("ean"),
                    },
                )
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
                },
            )
            return None


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
