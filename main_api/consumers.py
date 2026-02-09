from channels.generic.websocket import AsyncWebsocketConsumer
from urllib.parse import parse_qs
import json


class UploadProgressConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        url_kwargs = self.scope.get("url_route", {}).get("kwargs", {})
        job_id = url_kwargs.get("job_id")
        if not job_id:
            query_string = self.scope.get("query_string", b"").decode("utf-8")
            job_id = parse_qs(query_string).get("job_id", [None])[0]
        self.job_id = job_id or "default"
        self.group_name = f"{self.job_id}_upload"

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def ws_message(self, event):
        await self.send(
            text_data=json.dumps({
                "job_id": event["job_id"],
                "event": event["event"],
                "payload": event["payload"],
                "info": event["info"],
                "timestamp": event["timestamp"],
            })
        )

class DeleteProgressConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        print("DELETE PROGRESS CONNECTED")
        await self.channel_layer.group_add("delete_group", self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        await self.channel_layer.group_discard("delete_group", self.channel_name)

    async def delete_progress(self, event):
        """ """
        await self.send(text_data=json.dumps(event))
