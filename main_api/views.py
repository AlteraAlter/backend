import aiohttp
from uuid import uuid4
import asyncio
from adrf.views import APIView
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
import pandas as pd
from main_api.serializers import FileUploadSerializer, CombinedUploadSerializer
from main_api.src.controller.kaufland_controller import KauflandController
from main_api.src.servises.kaufland_upload_service import KauflandUploadService
from main_api.src.logger import log
from main_api.src.job_registry import cancel_job


async def _run_checker_job(controller_name: str, eans: list[str], job_id: str) -> None:
    async with aiohttp.ClientSession() as session:
        controller = KauflandController(session, controller_name)
        try:
            await controller.products_checker(eans, job_id=job_id)
        except Exception as e:
            log(
                f"checker job failed job_id={job_id} controller={controller_name} eans={eans} error={e}",
                save=True,
            )


async def _run_delete_job(controller_name: str, eans: list[str], job_id: str) -> None:
    async with aiohttp.ClientSession() as session:
        controller = KauflandController(session, controller_name)
        try:
            await controller.delete_all_products(eans, job_id=job_id)
        except Exception as e:
            await controller._send_task_progress(
                job_id,
                "delete",
                "job_completed",
                payload={
                    "total": len(eans),
                    "processed": 0,
                    "success": 0,
                    "failed": len(eans),
                },
                info=f"failed: {str(e)}",
            )


class MainOperationsView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = FileUploadSerializer

    async def get(self, request):
        return Response({"message": "ok"}, status=status.HTTP_200_OK)

    async def post(self, request):
        serializer = FileUploadSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        file = serializer.validated_data.get("file")
        ean = serializer.validated_data.get("ean")
        job_id = serializer.validated_data.get("job_id")
        mode = serializer.validated_data["mode"]
        controller = serializer.validated_data["controller"]
        log(f"Contoller: {controller}")

        if mode == "checker" and not file:
            single_ean = str(ean).strip() if ean is not None else ""
            if not single_ean:
                return Response(
                    {"error": "ean is required for checker"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not job_id:
                job_id = uuid4().hex
            try:
                async with aiohttp.ClientSession() as session:
                    kaufland_controller = KauflandController(session, controller)
                    checker_results = await kaufland_controller.products_checker(
                        [single_ean], job_id=job_id
                    )

                return Response(
                    {
                        "message": "checker completed",
                        "job_id": job_id,
                        "eans": [single_ean],
                        "results": checker_results,
                    },
                    status=status.HTTP_200_OK,
                )
            except Exception as e:
                log(
                    f"single checker failed job_id={job_id} ean={single_ean} error={e}",
                    save=True,
                )
                return Response(
                    {
                        "error": f"single checker failed: {str(e)}",
                        "job_id": job_id,
                        "ean": single_ean,
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        filename = file.name.lower()
        if filename.endswith(".csv"):
            df = pd.read_csv(file)
        elif filename.endswith(".xlsx"):
            df = pd.read_excel(file)
        else:
            return Response(
                {"error": "unsupported file format"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            async with aiohttp.ClientSession() as session:
                kaufland_controller = KauflandController(session, controller)

                if set(df.columns) == {"ean"}:
                    df = df.astype({"ean": str})
                    eans_list = list(set(df["ean"].tolist()))

                    if mode == "delete":
                        if not job_id:
                            job_id = uuid4().hex
                        asyncio.create_task(
                            _run_delete_job(controller, eans_list, job_id)
                        )
                        return Response(
                            {
                                "message": "delete job started",
                                "job_id": job_id,
                            },
                            status=status.HTTP_202_ACCEPTED,
                        )

                    if mode == "checker":
                        if not job_id:
                            job_id = uuid4().hex
                        checker_results = await kaufland_controller.products_checker(
                            eans_list, job_id=job_id
                        )
                        return Response(
                            {
                                "message": "checker completed",
                                "job_id": job_id,
                                "eans": eans_list,
                                "results": checker_results,
                                "last_result": (
                                    checker_results[-1] if checker_results else None
                                ),
                            },
                            status=status.HTTP_200_OK,
                        )

                    return Response(
                        {"info": "mode is not allowed for ean-only file"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                if set(df.columns) >= {"ean", "price"}:
                    df = df.astype({"ean": str, "price": float})
                    eans_prices = dict(zip(df["ean"], df["price"]))

                    if mode == "delete":
                        if not job_id:
                            job_id = uuid4().hex
                        asyncio.create_task(
                            _run_delete_job(
                                controller, list(eans_prices.keys()), job_id
                            )
                        )
                        return Response(
                            {
                                "message": "delete job started",
                                "job_id": job_id,
                            },
                            status=status.HTTP_202_ACCEPTED,
                        )

                    if mode == "change_price":
                        result = await kaufland_controller.update_price(eans_prices)
                        if result:
                            return Response(
                                "all prices updated", status=status.HTTP_200_OK
                            )
                        return Response(
                            "something went wrong",
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        )

                return Response(
                    {"error": "file must include column 'ean' (and optional 'price')"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        except Exception as e:
            log(
                f"file processing failed controller={controller} mode={mode} input_ean={ean} error={e}",
                save=True,
            )
            return Response(
                {
                    "error": f"file processing error: {str(e)}",
                    "input_ean": str(ean).strip() if ean is not None else None,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )


class UploadCollectionsViaJsonView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CombinedUploadSerializer

    async def get(self, request):
        return Response(
            {"info": "Kaufland uploader via json"}, status=status.HTTP_200_OK
        )

    async def post(self, request):
        log("<------Post method initialized----->")
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        controller_name = serializer.validated_data["controller"]
        mode = serializer.validated_data["mode"]
        json_content = serializer.validated_data.get("json_content")
        job_id = serializer.validated_data.get("job_id")

        if json_content is None:
            return Response(
                {"error": "invalid json content"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if isinstance(json_content, dict):
            json_content = [json_content]

        async with aiohttp.ClientSession() as session:
            controller: KauflandController = KauflandController(
                session, controller_name
            )
            service = KauflandUploadService(controller)
            if mode == "upload_product":
                if not job_id:
                    job_id = uuid4().hex
                result = await service.upload_single(json_content[0], job_id=job_id)

                return Response(
                    (
                        {"message": "success", "job_id": job_id}
                        if result
                        else {"message": "failed", "job_id": job_id}
                    ),
                    status=200 if result else 500,
                )
            if mode == "upload_collection":
                log("Massive upload")
                if not job_id:
                    job_id = uuid4().hex
                result = await service.upload_collection(json_content, job_id=job_id)

                if result is True:
                    return Response(
                        {"message": "success", "job_id": job_id},
                        status=status.HTTP_200_OK,
                    )
                elif result is False:
                    return Response(
                        {"message": "partial success", "job_id": job_id},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    )
                else:
                    return Response(
                        {"message": "all failed", "job_id": job_id},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    )
        return Response({"error": "invalid mode"}, status=status.HTTP_400_BAD_REQUEST)


class ProtectedView(APIView):
    permission_classes = [IsAuthenticated]

    async def get(self, request):
        return Response({"message": "ok"}, status=status.HTTP_200_OK)


class StopJobView(APIView):
    permission_classes = [IsAuthenticated]

    async def post(self, request):
        job_id = str(request.data.get("job_id") or "").strip()
        if not job_id:
            return Response(
                {"error": "job_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        stopped = await cancel_job(job_id)
        if not stopped:
            return Response(
                {"error": "unable to stop job"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({"message": "stop requested", "job_id": job_id}, status=200)
