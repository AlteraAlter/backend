import asyncio
import os
import re
from uuid import uuid4

import aiohttp
from adrf.views import APIView
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from main_api.serializers import RetrieveProductSerializer
from main_api.external_serializer import ProductDataSerializer
from main_api.services.aftercool_service import (
    AftercoolAuthError,
    AftercoolTransportError,
    AftercoolUpstreamError,
)
from main_api.services.aftercool_price_sync_service import AftercoolPriceSyncService
from main_api.src.controller.kaufland_controller import KauflandController
from main_api.src.controller.rest_api_controller import RestApiController
from main_api.src.job_registry import clear_cancel, is_cancelled, register_running_job, unregister_running_job
from main_api.src.logger import log


try:
    MAX_CONCURRENT_JOBS = max(1, int(os.getenv("MAX_CONCURRENT_JOBS", "3")))
except ValueError:
    MAX_CONCURRENT_JOBS = 3
JOB_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_JOBS)


async def _send_aftercool_sync_progress(
    controller: KauflandController,
    job_id: str,
    event: str,
    payload: dict | None = None,
    info: str | None = None,
) -> None:
    payload_with_task = dict(payload or {})
    payload_with_task.setdefault("task", "price_sync")
    await controller._ws_message_send(
        group_name=f"{job_id}_checker",
        job_id=job_id,
        event=event,
        payload=payload_with_task,
        info=info,
    )


async def _run_aftercool_price_sync_job(
    controller_name: str,
    job_id: str,
    username: str | None,
) -> None:
    async with JOB_SEMAPHORE:
        async with aiohttp.ClientSession() as session:
            controllers_by_account = {
                "jv": KauflandController(session, "jv"),
                "xl": KauflandController(session, "xl"),
            }
            controller = (
                controllers_by_account.get(controller_name)
                or controllers_by_account["jv"]
            )
            sync_service = AftercoolPriceSyncService(
                controller=controller,
                controllers_by_account=controllers_by_account,
            )

            async def progress_sender(
                event: str,
                payload: dict | None = None,
                info: str | None = None,
            ) -> None:
                await _send_aftercool_sync_progress(
                    controller,
                    job_id,
                    event,
                    payload=payload,
                    info=info,
                )

            async def cancelled() -> bool:
                return await is_cancelled(job_id)

            await clear_cancel(job_id)
            await register_running_job(job_id)
            try:
                await sync_service.run(
                    job_id=job_id,
                    progress_sender=progress_sender,
                    is_cancelled=cancelled,
                )
            except (
                AftercoolAuthError,
                AftercoolTransportError,
                AftercoolUpstreamError,
            ) as exc:
                await _send_aftercool_sync_progress(
                    controller,
                    job_id,
                    "job_failed",
                    payload={
                        "total": 0,
                        "processed": 0,
                        "success": 0,
                        "failed": 1,
                        "error": 1,
                        "updated": 0,
                        "skipped": 0,
                        "not_found": 0,
                        "failed_eans": [],
                    },
                    info=str(exc),
                )
                log(
                    f"aftercool price sync failed job_id={job_id} controller={controller_name} error={exc}",
                    save=True,
                    level="error",
                )
            except Exception as exc:
                await _send_aftercool_sync_progress(
                    controller,
                    job_id,
                    "job_failed",
                    payload={
                        "total": 0,
                        "processed": 0,
                        "success": 0,
                        "failed": 1,
                        "error": 1,
                        "updated": 0,
                        "skipped": 0,
                        "not_found": 0,
                        "failed_eans": [],
                    },
                    info="unexpected error",
                )
                log(
                    f"aftercool price sync unexpected failure job_id={job_id} controller={controller_name} error={exc}",
                    save=True,
                    level="error",
                )
            finally:
                await unregister_running_job(job_id)


class AftercoolLoginView(APIView):
    permission_classes = [AllowAny]

    async def get(self, request):
        controller_name = os.getenv("AFTERCOOL_TARGET_CONTROLLER", "jv").strip().lower()
        if controller_name not in {"jv", "xl"}:
            controller_name = "jv"

        username = (
            request.user.get_username()
            if getattr(request.user, "is_authenticated", False)
            else None
        )
        job_id = uuid4().hex
        asyncio.create_task(
            _run_aftercool_price_sync_job(
                controller_name=controller_name,
                job_id=job_id,
                username=username,
            )
        )
        return Response(
            {
                "message": "aftercool price sync job started",
                "job_id": job_id,
                "controller": controller_name,
                "ws_task": "checker",
                "progress_ws": f"/ws/checker-progress/{job_id}/",
                "change_log_file": "logs/aftercool_price_changes.csv",
            },
            status=status.HTTP_202_ACCEPTED,
        )


class RetreiveProductView(APIView):
    serializer_class = RetrieveProductSerializer
    permission_classes = [AllowAny]

    async def get(self, request):
        serializer = self.serializer_class(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        ean = serializer.validated_data["ean"]
        controller = serializer.validated_data["controller"]

        async with aiohttp.ClientSession() as session:
            kaufland_controller = KauflandController(session, controller)
            result = await kaufland_controller.get_product_by_ean(ean)

        return Response(result, status=status.HTTP_200_OK)


class PatchProductView(APIView):
    serializer_class = ProductDataSerializer
    permission_classes = [AllowAny]

    async def get(self, request):
        return Response({"message": "ok"}, status=status.HTTP_200_OK)

    async def put(self, request):
        return Response({"message": "ok"}, status=status.HTTP_200_OK)
    
    async def patch(self, request):
        items = request.data if isinstance(request.data, list) else [request.data]
        results = []

        for item in items:
            serializer = self.serializer_class(data=item)
            serializer.is_valid(raise_exception=True)

            validated_data = serializer.validated_data
            ean = validated_data["ean"]
            controller = validated_data["controller"]

            attributes = {}
            if "title" in validated_data:
                attributes["title"] = [validated_data["title"]]
            if "description" in validated_data:
                attributes["description"] = [validated_data["description"]]
            if "picture_urls" in validated_data:
                attributes["picture_urls"] = [validated_data["picture_urls"]]


            storefront = str(validated_data.get("storefront")) if validated_data.get("storefront") else "de"
            
            payload = {"ean": [ean], "attributes": attributes}

            response_item = {
                "received_data": validated_data,
                "product_data_updated": False,
                "price_updated": False,
            }

            if attributes:
                async with aiohttp.ClientSession() as client:
                    rac = RestApiController(controller=controller, session=client)
                    api_response = await rac.send_request(
                        method="PATCH",
                        endpoint=f"/product-data?locale={self.to_locale_value(storefront)}",
                        json=payload,
                    )
                response_item["product_data_updated"] = True
                response_item["product_data_response"] = api_response

            if validated_data.get("unit_id"):
                unit_id: str = validated_data.get("unit_id")
                price = validated_data.get("price")

                if unit_id and price is not None:
                    unit_endpoint = (
                        f"/units/{unit_id}?storefront={storefront}"
                    )
                    async with aiohttp.ClientSession() as client:
                        rac = RestApiController(controller=controller, session=client)
                        payload = rac.make_price_payload(
                            storefront=storefront,
                            price=float(price),
                        )
                        
                        try:
                            price_response = await rac.send_request(
                                method="PATCH",
                                endpoint=unit_endpoint,
                                json=payload,
                            )
                            
                        except Exception as exc:
                            return Response(f"Failed to update price: {exc}, json = {payload}", status=status.HTTP_400_BAD_REQUEST)

                    response_item["price_updated"] = True
                    response_item["price_response"] = price_response

                results.append(response_item)

        if isinstance(request.data, list):
            return Response({"results": results}, status=status.HTTP_200_OK)
        
        return Response(results[0], status=status.HTTP_200_OK)

    
    def to_locale_value(self, storefront: str) -> str:
        match storefront:
            case "de": return "de-DE"
            case "cz": return "cs-CZ"
            case "sk": return "sk-SK"
            case "at": return "de-AT"
            case "pl": return "pl-PL"
            case "fr": return "fr-FR"
            case "it": return "it-IT"
            case _: return "de-DE"
