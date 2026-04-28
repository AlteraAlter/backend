from __future__ import annotations

import asyncio
import csv
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from django.conf import settings

from main_api.services.aftercool_service import (
    AftercoolAuthError,
    AftercoolService,
    AftercoolTransportError,
    AftercoolUpstreamError,
    AftercoolProductsQuery,
)
from main_api.src.controller.kaufland_controller import KauflandController
from main_api.src.logger import log

ProgressSender = Callable[[str, dict[str, Any] | None, str | None], Awaitable[None]]
CancelChecker = Callable[[], Awaitable[bool]]


@dataclass
class AftercoolPriceSyncResult:
    total: int = 0
    processed: int = 0
    updated: int = 0
    skipped: int = 0
    not_found: int = 0
    failed: int = 0
    fetch_batches: int = 0
    failed_eans: list[str] = field(default_factory=list)
    cancelled: bool = False


class AftercoolPriceSyncService:
    def __init__(
        self,
        *,
        controller: KauflandController | None = None,
        controllers_by_account: dict[str, KauflandController] | None = None,
        aftercool_service: AftercoolService | None = None,
        ws_task_name: str = "price_sync",
        change_log_path: str | None = None,
        dataset: str = "lister",
        page_size: int = 500,
        max_batches_per_account: int = 500,
        fetch_retries: int = 3,
        process_retries: int = 2,
        retry_backoff_sec: float = 1.0,
        accounts_order: tuple[str, ...] = ("jv", "xl"),
    ):
        self.aftercool_service = aftercool_service or AftercoolService()
        self.ws_task_name = ws_task_name
        self.dataset = str(dataset or "lister").strip() or "lister"
        self.page_size = max(1, int(page_size))
        self.max_batches_per_account = max(1, int(max_batches_per_account))
        self.fetch_retries = max(0, int(fetch_retries))
        self.process_retries = max(0, int(process_retries))
        self.retry_backoff_sec = max(0.1, float(retry_backoff_sec))
        self.accounts_order = [
            str(account or "").strip().lower()
            for account in accounts_order
            if str(account or "").strip()
        ]

        base_dir = (
            str(getattr(settings, "BASE_DIR", os.getcwd()))
            if getattr(settings, "configured", False)
            else os.getcwd()
        )
        default_change_log = os.path.join(
            base_dir, "logs", "aftercool_price_changes.csv"
        )
        self.change_log_path = (
            change_log_path
            or os.getenv("AFTERCOOL_PRICE_CHANGE_LOG_PATH")
            or default_change_log
        )

        normalized_controllers: dict[str, KauflandController] = {}
        if controllers_by_account:
            for account, current_controller in controllers_by_account.items():
                account_key = str(account or "").strip().lower()
                if account_key and current_controller is not None:
                    normalized_controllers[account_key] = current_controller

        if controller is not None:
            controller_key = (
                str(getattr(controller, "version", "")).strip().lower() or "jv"
            )
            normalized_controllers.setdefault(controller_key, controller)

        if not normalized_controllers:
            raise ValueError(
                "AftercoolPriceSyncService requires at least one controller"
            )

        self.controllers_by_account = normalized_controllers

        for account in list(self.controllers_by_account.keys()):
            if account not in self.accounts_order:
                self.accounts_order.append(account)

    async def run(
        self,
        *,
        job_id: str,
        progress_sender: ProgressSender | None = None,
        is_cancelled: CancelChecker | None = None,
    ) -> AftercoolPriceSyncResult:
        result = AftercoolPriceSyncResult()

        if is_cancelled is not None and await is_cancelled():
            result.cancelled = True
            return await self._fail_stopped(result, progress_sender)

        await self._send_progress(
            progress_sender,
            "job_started",
            payload={
                "total": 0,
                "controller": "multi",
                "accounts": self.accounts_order,
                "page_size": self.page_size,
            },
        )

        session_cookie = await self._with_retries(
            operation=lambda: self.aftercool_service.login(),
            retries=self.fetch_retries,
            retry_exceptions=(AftercoolAuthError, AftercoolTransportError),
            retry_label="aftercool login",
        )

        last_progress_emit_at: float | None = None

        for account in self.accounts_order:
            if is_cancelled is not None and await is_cancelled():
                result.cancelled = True
                return await self._fail_stopped(result, progress_sender)

            controller = self.controllers_by_account.get(account)
            if controller is None:
                log(
                    f"aftercool sync skipped account={account} no controller mapping",
                                        level="warning",
                )
                continue

            log(
                f"aftercool sync account_started account={account}",
                                level="info",
            )
            await self._send_progress(
                progress_sender,
                "progress",
                payload={
                    "status": "running",
                    "stage": "account_started",
                    "account": account,
                    "item": None,
                    "message": f"account={account}",
                },
            )

            batch_index = 0
            offset = 0

            while batch_index < self.max_batches_per_account:
                if is_cancelled is not None and await is_cancelled():
                    result.cancelled = True
                    return await self._fail_stopped(result, progress_sender)

                query = AftercoolProductsQuery(
                    account=account,
                    dataset=self.dataset,
                    include_row=1,
                    limit=self.page_size,
                    offset=offset,
                )

                chunk = await self._with_retries(
                    operation=lambda: self.aftercool_service.get_products(
                        session_cookie, query=query
                    ),
                    retries=self.fetch_retries,
                    retry_exceptions=(AftercoolTransportError, AftercoolUpstreamError),
                    retry_label=f"aftercool fetch account={account} offset={offset}",
                )

                batch_index += 1
                result.fetch_batches += 1

                fetched_count = len(chunk)
                log(
                    f"aftercool fetched account={account} batch={batch_index} offset={offset} fetched={fetched_count}",
                                        level="info",
                )

                await self._send_progress(
                    progress_sender,
                    "progress",
                    payload={
                        "status": "running",
                        "stage": "fetched_batch",
                        "account": account,
                        "item": None,
                        "message": f"account={account} offset={offset} fetched={fetched_count}",
                    },
                )

                if not chunk:
                    break

                pairs = self.aftercool_service.extract_ean_price_pairs(chunk)
                result.total += len(pairs)

                log(
                    f"aftercool parsed account={account} batch={batch_index} ean_price_pairs={len(pairs)}",
                                        level="info",
                )
                await self._send_progress(
                    progress_sender,
                    "job_progress",
                    payload={
                        "total": max(result.total, result.processed),
                        "processed": result.processed,
                        "success": result.updated,
                        "error": result.failed,
                        "updated": result.updated,
                        "skipped": result.skipped,
                        "not_found": result.not_found,
                        "status": "fetching_aftercool",
                        "account": account,
                        "controller": controller.version,
                        "batch": batch_index,
                        "offset": offset,
                        "fetched": fetched_count,
                    },
                )

                for pair in pairs:
                    if is_cancelled is not None and await is_cancelled():
                        result.cancelled = True
                        return await self._fail_stopped(result, progress_sender)

                    ean = str(pair.get("ean") or "").strip()
                    aftercool_price = self._to_float(pair.get("price"))
                    if not ean or aftercool_price is None:
                        result.skipped += 1
                        result.processed += 1
                        continue

                    try:
                        action, storefront, kaufland_price, action_detail = (
                            await self._with_retries(
                                operation=lambda: self._process_single_pair(
                                    job_id=job_id,
                                    account=account,
                                    controller=controller,
                                    ean=ean,
                                    aftercool_price=aftercool_price,
                                ),
                                retries=self.process_retries,
                                retry_exceptions=(Exception,),
                                retry_label=f"ean process account={account} ean={ean}",
                                log_retries=False,
                            )
                        )
                    except Exception as exc:
                        action = "failed"
                        storefront = None
                        kaufland_price = None
                        action_detail = f"unexpected_error={exc}"

                    if action == "updated":
                        result.updated += 1
                    elif action == "not_found":
                        result.not_found += 1
                        result.skipped += 1
                    elif action == "failed":
                        result.failed += 1
                        result.failed_eans.append(ean)
                    else:
                        result.skipped += 1

                    summary_parts = [
                        f"aftercool sync ean={ean}",
                        f"account={account}",
                        f"status={action}",
                    ]
                    if storefront:
                        summary_parts.append(f"storefront={storefront}")
                    if kaufland_price is not None:
                        summary_parts.append(
                            f"kaufland_price={round(kaufland_price, 2)}"
                        )
                    summary_parts.append(f"aftercool_price={round(aftercool_price, 2)}")
                    if action == "updated" and kaufland_price is not None:
                        summary_parts.append(f"changed_from={round(kaufland_price, 2)}")
                        summary_parts.append(f"changed_to={round(aftercool_price, 2)}")
                    if action_detail:
                        summary_parts.append(f"detail={action_detail}")
                    log(" ".join(summary_parts), level="info")

                    result.processed += 1

                    if controller._should_emit_progress(
                        processed=result.processed,
                        total=max(result.total, result.processed),
                        last_emit_at=last_progress_emit_at,
                    ):
                        await self._send_progress(
                            progress_sender,
                            "job_progress",
                            payload={
                                "total": max(result.total, result.processed),
                                "processed": result.processed,
                                "success": result.updated,
                                "error": result.failed,
                                "updated": result.updated,
                                "skipped": result.skipped,
                                "not_found": result.not_found,
                                "ean": ean,
                                "status": action,
                                "aftercool_price": aftercool_price,
                                "kaufland_price": kaufland_price,
                                "storefront": storefront,
                                "account": account,
                                "controller": controller.version,
                            },
                        )
                        last_progress_emit_at = time.monotonic()

                offset += self.page_size

            log(
                f"aftercool sync account_completed account={account} processed={result.processed} updated={result.updated} failed={result.failed}",
                                level="info",
            )
            await self._send_progress(
                progress_sender,
                "progress",
                payload={
                    "status": "running",
                    "stage": "account_completed",
                    "account": account,
                    "item": None,
                    "message": f"account={account} processed={result.processed} updated={result.updated}",
                },
            )

        await self._send_progress(
            progress_sender,
            "job_completed",
            payload={
                "total": max(result.total, result.processed),
                "processed": result.processed,
                "success": result.updated,
                "failed": result.failed,
                "error": result.failed,
                "updated": result.updated,
                "skipped": result.skipped,
                "not_found": result.not_found,
                "fetch_batches": result.fetch_batches,
                "failed_eans": result.failed_eans,
            },
            info="success" if result.failed == 0 else "partial_or_failed",
        )
        return result

    async def _process_single_pair(
        self,
        *,
        job_id: str,
        account: str,
        controller: KauflandController,
        ean: str,
        aftercool_price: float,
    ) -> tuple[str, str | None, float | None, str | None]:
        main_data = await controller._fetch_main_data_by_ean(ean)
        kaufland_price, storefront = self._pick_kaufland_reference_price(main_data)

        if kaufland_price is None:
            return "not_found", storefront, kaufland_price, "not_found_on_kaufland"

        if aftercool_price <= kaufland_price:
            return "skipped", storefront, kaufland_price, "aftercool_not_higher"

        unit_ids = await controller._fetch_unit_id_by_ean(ean)
        if not unit_ids:
            return "failed", storefront, kaufland_price, "no_unit_ids"

        units_to_update = await self._collect_units_requiring_update(
            controller=controller,
            unit_ids=unit_ids,
            main_data=main_data,
            aftercool_price=aftercool_price,
        )
        if not units_to_update:
            return "skipped", storefront, kaufland_price, "no_price_change_required"

        updated = await controller._update_price_by_unit_id(
            ean,
            aftercool_price,
            units_to_update,
        )
        if not updated:
            return "failed", storefront, kaufland_price, "update_returned_false"

        self._append_change_log(
            job_id=job_id,
            ean=ean,
            controller=controller.version,
            old_price=kaufland_price,
            new_price=aftercool_price,
            storefront=storefront,
        )
        return "updated", storefront, kaufland_price, "price_changed"

    async def _collect_units_requiring_update(
        self,
        *,
        controller: KauflandController,
        unit_ids: dict[str, str],
        main_data: list[dict[str, Any]] | None,
        aftercool_price: float,
    ) -> dict[str, str]:
        current_prices = self._build_storefront_price_map(main_data)
        units_to_update: dict[str, str] = {}

        for storefront_raw, unit_id in unit_ids.items():
            storefront = self._normalize_storefront(storefront_raw)
            if not storefront:
                continue
            target_listing_price = int(
                await controller._make_price(
                    storefront=storefront, price=aftercool_price
                )
            )
            current_price = current_prices.get(storefront)
            if current_price is None:
                units_to_update[storefront_raw] = unit_id
                continue
            current_listing_price = int(round(current_price * 100))
            if current_listing_price != target_listing_price:
                units_to_update[storefront_raw] = unit_id

        return units_to_update

    async def _with_retries(
        self,
        *,
        operation: Callable[[], Awaitable[Any]],
        retries: int,
        retry_exceptions: tuple[type[BaseException], ...],
        retry_label: str,
        log_retries: bool = True,
    ) -> Any:
        max_attempts = max(1, retries + 1)
        for attempt in range(1, max_attempts + 1):
            try:
                return await operation()
            except retry_exceptions as exc:
                if attempt >= max_attempts:
                    raise
                sleep_time = self.retry_backoff_sec * (2 ** (attempt - 1))
                if log_retries:
                    log(
                        f"retry attempt={attempt}/{max_attempts - 1} label='{retry_label}' error={exc}",
                                                level="warning",
                    )
                await asyncio.sleep(sleep_time)

    async def _fail_stopped(
        self,
        result: AftercoolPriceSyncResult,
        progress_sender: ProgressSender | None,
    ) -> AftercoolPriceSyncResult:
        await self._send_progress(
            progress_sender,
            "job_failed",
            payload={
                "total": max(result.total, result.processed),
                "processed": result.processed,
                "success": result.updated,
                "failed": result.failed,
                "error": result.failed,
                "updated": result.updated,
                "skipped": result.skipped,
                "not_found": result.not_found,
                "fetch_batches": result.fetch_batches,
                "failed_eans": result.failed_eans,
            },
            info="stopped",
        )
        return result

    async def _send_progress(
        self,
        progress_sender: ProgressSender | None,
        event: str,
        *,
        payload: dict[str, Any] | None = None,
        info: str | None = None,
    ) -> None:
        if progress_sender is None:
            return
        payload_with_task = dict(payload or {})
        payload_with_task.setdefault("task", self.ws_task_name)
        await progress_sender(event, payload_with_task, info)

    @staticmethod
    def _pick_kaufland_reference_price(
        items: list[dict[str, Any]] | None,
    ) -> tuple[float | None, str | None]:
        if not isinstance(items, list):
            return None, None
        normalized_items = [item for item in items if isinstance(item, dict)]
        if not normalized_items:
            return None, None

        preferred = sorted(
            normalized_items,
            key=lambda item: (
                0 if str(item.get("storefront") or "").strip().lower() == "de" else 1
            ),
        )
        for item in preferred:
            price = AftercoolPriceSyncService._to_float(item.get("price"))
            if price is None:
                continue
            storefront = str(item.get("storefront") or "").strip() or None
            return price, storefront

        return None, None

    @staticmethod
    def _normalize_storefront(value: Any) -> str | None:
        text = str(value or "").strip().lower()
        return text or None

    @staticmethod
    def _build_storefront_price_map(
        items: list[dict[str, Any]] | None,
    ) -> dict[str, float]:
        if not isinstance(items, list):
            return {}
        prices: dict[str, float] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            storefront = AftercoolPriceSyncService._normalize_storefront(
                item.get("storefront")
            )
            if not storefront:
                continue
            price = AftercoolPriceSyncService._to_float(item.get("price"))
            if price is None:
                continue
            prices[storefront] = price
        return prices

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip()
        if not text:
            return None
        text = text.replace(",", ".")
        try:
            return float(text)
        except ValueError:
            return None

    def _append_change_log(
        self,
        *,
        job_id: str,
        ean: str,
        controller: str,
        old_price: float,
        new_price: float,
        storefront: str | None,
    ) -> None:
        directory = os.path.dirname(self.change_log_path)
        if directory:
            os.makedirs(directory, exist_ok=True)

        file_exists = os.path.exists(self.change_log_path)
        header = [
            "timestamp",
            "job_id",
            "controller",
            "ean",
            "storefront",
            "kaufland_price",
            "aftercool_price",
        ]
        row = {
            "timestamp": datetime.now(ZoneInfo("Asia/Almaty")).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "job_id": job_id,
            "controller": controller,
            "ean": ean,
            "storefront": storefront or "",
            "kaufland_price": round(old_price, 2),
            "aftercool_price": round(new_price, 2),
        }

        with open(self.change_log_path, "a", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=header)
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
