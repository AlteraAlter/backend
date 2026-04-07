from channels.generic.websocket import AsyncWebsocketConsumer
from urllib.parse import parse_qs
import json
import logging


logger = logging.getLogger(__name__)


class UploadProgressConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        url_kwargs = self.scope.get("url_route", {}).get("kwargs", {})
        job_id = url_kwargs.get("job_id")
        if not job_id:
            query_string = self.scope.get("query_string", b"").decode("utf-8")
            job_id = parse_qs(query_string).get("job_id", [None])[0]
        self.job_id = str(job_id or "").strip()
        if not self.job_id:
            logger.warning(
                "ws_upload_close_missing_job_id path=%s client=%s",
                self.scope.get("path"),
                self.scope.get("client"),
            )
            await self.close(code=4400)
            return
        self.group_name = f"{self.job_id}_upload"

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        logger.info(
            "ws_upload_connected job_id=%s group=%s channel=%s client=%s",
            self.job_id,
            self.group_name,
            self.channel_name,
            self.scope.get("client"),
        )

    async def disconnect(self, close_code):
        group_name = getattr(self, "group_name", None)
        if group_name:
            await self.channel_layer.group_discard(group_name, self.channel_name)
        logger.info(
            "ws_upload_disconnected job_id=%s group=%s channel=%s close_code=%s",
            getattr(self, "job_id", None),
            group_name,
            self.channel_name,
            close_code,
        )

    async def ws_message(self, event):
        await self.send(
            text_data=json.dumps(
                {
                    "job_id": event["job_id"],
                    "event": event["event"],
                    "payload": event["payload"],
                    "info": event["info"],
                    "timestamp": event["timestamp"],
                }
            )
        )


class CheckerProgressConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        url_kwargs = self.scope.get("url_route", {}).get("kwargs", {})
        job_id = url_kwargs.get("job_id")
        if not job_id:
            query_string = self.scope.get("query_string", b"").decode("utf-8")
            job_id = parse_qs(query_string).get("job_id", [None])[0]
        self.job_id = str(job_id or "").strip()
        if not self.job_id:
            logger.warning(
                "ws_checker_close_missing_job_id path=%s client=%s",
                self.scope.get("path"),
                self.scope.get("client"),
            )
            await self.close(code=4400)
            return
        self.group_name = f"{self.job_id}_checker"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        logger.info(
            "ws_checker_connected job_id=%s group=%s channel=%s client=%s",
            self.job_id,
            self.group_name,
            self.channel_name,
            self.scope.get("client"),
        )

    async def disconnect(self, close_code):
        group_name = getattr(self, "group_name", None)
        if group_name:
            await self.channel_layer.group_discard(group_name, self.channel_name)
        logger.info(
            "ws_checker_disconnected job_id=%s group=%s channel=%s close_code=%s",
            getattr(self, "job_id", None),
            group_name,
            self.channel_name,
            close_code,
        )

    async def ws_message(self, event):
        await self.send(
            text_data=json.dumps(
                {
                    "job_id": event["job_id"],
                    "event": event["event"],
                    "payload": event["payload"],
                    "info": event["info"],
                    "timestamp": event["timestamp"],
                }
            )
        )


class DeleteProgressConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        url_kwargs = self.scope.get("url_route", {}).get("kwargs", {})
        job_id = url_kwargs.get("job_id")
        if not job_id:
            query_string = self.scope.get("query_string", b"").decode("utf-8")
            job_id = parse_qs(query_string).get("job_id", [None])[0]
        self.job_id = str(job_id or "").strip() or None
        if self.job_id:
            self.group_name = f"{self.job_id}_delete"
        else:
            self.group_name = "delete_group"

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        logger.info(
            "ws_delete_connected job_id=%s group=%s channel=%s client=%s",
            self.job_id,
            self.group_name,
            self.channel_name,
            self.scope.get("client"),
        )

    async def disconnect(self, code):
        group_name = getattr(self, "group_name", None)
        if group_name:
            await self.channel_layer.group_discard(group_name, self.channel_name)
        logger.info(
            "ws_delete_disconnected job_id=%s group=%s channel=%s close_code=%s",
            getattr(self, "job_id", None),
            group_name,
            self.channel_name,
            code,
        )

    async def delete_progress(self, event):
        """ """
        await self.send(text_data=json.dumps(event))

    async def delete_message(self, event):
        await self.send(text_data=json.dumps(event))

    async def ws_message(self, event):
        await self.send(
            text_data=json.dumps(
                {
                    "job_id": event["job_id"],
                    "event": event["event"],
                    "payload": event["payload"],
                    "info": event["info"],
                    "timestamp": event["timestamp"],
                }
            )
        )
