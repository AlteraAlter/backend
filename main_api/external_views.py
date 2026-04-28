import asyncio
import os
from uuid import uuid4

import aiohttp
from adrf.views import APIView
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from main_api.serializers import RetrieveProductSerializer
from main_api.services.aftercool_service import (
    AftercoolAuthError,
    AftercoolTransportError,
    AftercoolUpstreamError,
)
from main_api.services.aftercool_price_sync_service import AftercoolPriceSyncService
from main_api.src.controller.kaufland_controller import KauflandController
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


class ChangeProductView(APIView):

    async def get(self, request):
        return Response({"message": "ok"}, status=status.HTTP_200_OK)

    async def post(self, request):

        data = request.data

        return Response({"received_data": data}, status=status.HTTP_200_OK)
