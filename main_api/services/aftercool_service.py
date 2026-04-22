from __future__ import annotations
from dataclasses import dataclass
import re
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from main_api.src.logger import log


class AftercoolError(Exception):
    """Базовая ошибка интеграции Aftercool."""


class AftercoolTransportError(AftercoolError):
    """Сетевая/транспортная ошибка."""


class AftercoolAuthError(AftercoolError):
    """Ошибка аутентификации в Aftercool."""


class AftercoolUpstreamError(AftercoolError):
    """Ошибка ответа внешнего сервиса."""

    def __init__(self, message: str, *, status_code: int):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class AftercoolProductsQuery:
    account: str = ""
    dataset: str = ""
    factory_id: str = ""
    q: str = ""
    limit: int = 1
    offset: int = 0
    include_row: int = 1

    def as_params(self) -> dict[str, str]:
        return {
            "account": self.account,
            "dataset": self.dataset,
            "factory_id": self.factory_id,
            "q": self.q,
            "limit": str(self.limit),
            "offset": str(self.offset),
            "include_row": str(self.include_row),
        }


class AftercoolService:
    def __init__(
        self,
        *,
        login_url: str = "https://aftercool.de/auth/login",
        products_url: str = "https://aftercool.de/api/products",
        username: str = "Miras",
        password: str = "Miras112112",
        timeout: httpx.Timeout | None = None,
    ):
        self.login_url = login_url
        self.products_url = products_url
        self.username = username
        self.password = password
        self.timeout = (
            timeout
            if timeout
            else httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=5.0)
        )

    async def login(self) -> str:
        log("aftercool login started", save=False, level="debug")
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url=self.login_url,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    json={
                        "username": self.username,
                        "password": self.password,
                    },
                )
                if response.status_code != 200:
                    raise AftercoolAuthError(
                        f"aftercool auth failed with status {response.status_code}"
                    )
                session = dict(client.cookies).get("session")
                if not session:
                    raise AftercoolAuthError(
                        "aftercool auth succeeded but no session cookie"
                    )
                log("aftercool login completed", save=False, level="debug")
                return session
        except (httpx.ConnectTimeout, httpx.TimeoutException) as exc:
            log("timeout while logging in to aftercool", save=True, level="error")
            raise AftercoolTransportError(
                "timeout while logging in to aftercool"
            ) from exc
        except httpx.RequestError as exc:
            log(
                "failed to connect to aftercool login endpoint",
                save=True,
                level="error",
            )
            raise AftercoolTransportError(
                "failed to connect to aftercool login endpoint"
            ) from exc

    async def get_products(
        self,
        session: str,
        *,
        query: AftercoolProductsQuery | None = None,
    ) -> list[dict[str, Any]]:
        params = (query or AftercoolProductsQuery()).as_params()
        log(
            f"aftercool products fetch started with params={params}",
            save=False,
            level="debug",
        )
        try:
            async with httpx.AsyncClient(
                cookies={"session": session},
                timeout=self.timeout,
            ) as client:
                response = await client.get(
                    url=self.products_url,
                    params=params,
                )
        except (httpx.ConnectTimeout, httpx.TimeoutException) as exc:
            log(
                "timeout while fetching products from aftercool",
                save=True,
                level="error",
            )
            raise AftercoolTransportError(
                "timeout while fetching products from aftercool"
            ) from exc
        except httpx.RequestError as exc:
            log(
                "failed to connect to aftercool products endpoint",
                save=True,
                level="error",
            )
            raise AftercoolTransportError(
                "failed to connect to aftercool products endpoint"
            ) from exc

        if response.status_code != 200:
            log(
                f"aftercool returned non-200 on products request status={response.status_code}",
                save=True,
                level="error",
            )
            raise AftercoolUpstreamError(
                "aftercool returned non-200 on products request",
                status_code=response.status_code,
            )

        payload = response.json()
        items = payload.get("items")
        if not isinstance(items, list):
            raise AftercoolUpstreamError(
                "aftercool response has invalid 'items' shape",
                status_code=502,
            )
        log(
            f"aftercool products fetch completed, count={len(items)}",
            save=False,
            level="debug",
        )
        return items

    async def login_and_get_products(
        self,
        *,
        query: AftercoolProductsQuery | None = None,
        on_page: Callable[[int, int, int], Awaitable[None] | None] | None = None,
    ) -> list[dict[str, Any]]:
        session = await self.login()
        if query is not None:
            return await self.get_products(session, query=query)
        return await self.get_products_paginated(
            session,
            account="jv",
            dataset="lister",
            include_row=1,
            page_size=500,
            max_pages=40,
            on_page=on_page,
        )

    async def get_products_paginated(
        self,
        session: str,
        *,
        account: str = "jv",
        dataset: str = "lister",
        include_row: int = 1,
        page_size: int = 500,
        max_pages: int = 40,
        on_page: Callable[[int, int, int], Awaitable[None] | None] | None = None,
    ) -> list[dict[str, Any]]:
        safe_page_size = max(1, int(page_size))
        safe_max_pages = max(1, int(max_pages))
        all_items: list[dict[str, Any]] = []

        for page in range(safe_max_pages):
            query = AftercoolProductsQuery(
                account=account,
                dataset=dataset,
                include_row=include_row,
                limit=safe_page_size,
                offset=page * safe_page_size,
            )
            chunk = await self.get_products(session, query=query)
            if not chunk:
                break
            all_items.extend(chunk)
            if on_page is not None:
                maybe_awaitable = on_page(page + 1, len(all_items), len(chunk))
                if maybe_awaitable is not None:
                    await maybe_awaitable
            if len(chunk) < safe_page_size:
                break

        return all_items

    def extract_ean_price_pairs(
        self, items: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """
        Возвращает список с нормализованными ean/price из aftercool.
        Для дублей по EAN берется максимальная цена.
        """
        price_by_ean: dict[str, float] = {}
        for item in items:
            ean = self._extract_ean(item)
            if not ean:
                continue
            price = self._extract_price(item)
            if price is None:
                continue
            prev_price = price_by_ean.get(ean)
            if prev_price is None or price > prev_price:
                price_by_ean[ean] = price

        return [{"ean": ean, "price": price} for ean, price in price_by_ean.items()]

    @staticmethod
    def _extract_ean(item: dict[str, Any]) -> str | None:
        if not isinstance(item, dict):
            return None
        row = item.get("row") if isinstance(item.get("row"), dict) else {}
        candidates = (
            item.get("ean"),
            row.get("ean"),
            row.get("EAN"),
            row.get("Ean"),
        )
        for raw in candidates:
            normalized = AftercoolService._normalize_ean(raw)
            if normalized:
                return normalized

        custom_item_specifics = row.get("CustomItemSpecifics")
        extracted_from_specifics = (
            AftercoolService._extract_ean_from_custom_item_specifics(
                custom_item_specifics
            )
        )
        if extracted_from_specifics:
            return extracted_from_specifics

        fallback_candidates = (
            row.get("Artikelnummer"),
            item.get("artikelnummer"),
            row.get("ID"),
            item.get("product_id"),
        )
        for raw in fallback_candidates:
            normalized = AftercoolService._normalize_ean(raw)
            if normalized:
                return normalized
        return None

    @staticmethod
    def _extract_price(item: dict[str, Any]) -> float | None:
        if not isinstance(item, dict):
            return None
        row = item.get("row") if isinstance(item.get("row"), dict) else {}
        candidates = (
            item.get("price"),
            item.get("Price"),
            item.get("start_price"),
            item.get("Start price"),
            item.get("startpreis"),
            item.get("Startpreis"),
            row.get("price"),
            row.get("Price"),
            row.get("Start price"),
            row.get("StartPrice"),
            row.get("Startpreis"),
            row.get("SofortkaufenPreis"),
            row.get("Mindestgebot"),
            row.get("listing_price"),
            row.get("Listing price"),
        )
        for raw in candidates:
            parsed = AftercoolService._parse_price(raw)
            if parsed is not None:
                return parsed
        return None

    @staticmethod
    def _extract_ean_from_custom_item_specifics(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value)
        if not text.strip():
            return None

        # Preferred pattern: <Name><![CDATA[EAN]]></Name><Value><![CDATA[123...]]></Value>
        strict = re.search(
            r"<Name>\s*<!\[CDATA\[(?:ean|EAN)\]\]>\s*</Name>\s*"
            r"<Value>\s*<!\[CDATA\[(\d{8,14})\]\]>\s*</Value>",
            text,
            flags=re.IGNORECASE,
        )
        if strict:
            normalized = AftercoolService._normalize_ean(strict.group(1))
            if normalized:
                return normalized

        # Fallback: nearest 8-14 digit token near EAN word.
        loose = re.search(
            r"(?:ean|EAN)[^0-9]{0,80}(\d{8,14})",
            text,
            flags=re.IGNORECASE,
        )
        if loose:
            normalized = AftercoolService._normalize_ean(loose.group(1))
            if normalized:
                return normalized

        # Last fallback: any 13-digit sequence from specifics payload.
        generic = re.search(r"(?<!\d)(\d{13})(?!\d)", text)
        if generic:
            normalized = AftercoolService._normalize_ean(generic.group(1))
            if normalized:
                return normalized

        return None

    @staticmethod
    def _normalize_ean(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        if text.endswith(".0"):
            try:
                text = str(int(float(text)))
            except (TypeError, ValueError):
                pass
        digits = re.sub(r"\D", "", text)
        if len(digits) < 8:
            return None
        return digits

    @staticmethod
    def _parse_price(value: Any) -> float | None:
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            numeric = float(value)
            return round(numeric, 2) if numeric > 0 else None

        text = str(value).strip()
        if not text:
            return None
        text = text.replace("\u00a0", "").replace(" ", "")
        if "," in text and "." in text:
            if text.rfind(",") > text.rfind("."):
                text = text.replace(".", "").replace(",", ".")
            else:
                text = text.replace(",", "")
        else:
            text = text.replace(",", ".")

        match = re.search(r"-?\d+(?:\.\d+)?", text)
        if not match:
            return None
        try:
            numeric = float(match.group(0))
        except ValueError:
            return None
        if numeric <= 0:
            return None
        return round(numeric, 2)
