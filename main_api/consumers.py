from channels.generic.websocket import AsyncWebsocketConsumer
import json


class UploadProgressConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        print("UPLOAD PROGRESS CONNECTED")
        await self.channel_layer.group_add("upload_progress", self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard("upload_progress", self.channel_name)

    async def upload_progress(self, event):
        """
        event приходит из group_send
        """
        await self.send(text_data=json.dumps(event))


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
