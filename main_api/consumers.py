from channels.generic.websocket import AsyncWebsocketConsumer
import json


class RealTimeConsumer(AsyncWebsocketConsumer):
    """
        Консюмер который отвечает за передачу сообщений
        с бэка на фронт в реальном времени
        для проверки товара есть ли он или нет
    """
    async def connect(self):
        await self.channel_layer.group_add(
            "realtime_group",
            self.channel_name
        )
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            "realtime_group",
            self.channel_name
        )

    async def receive(self, text_data):
        text_data_json = json.loads(text_data)
        message = text_data_json.get("message", {})
        controller = text_data_json.get("controller", "")
        ean = text_data_json.get("ean", "")
        await self.channel_layer.group_send(
            "realtime_group",
            {
                'type': 'realtime_message',
                'message': message,
                'controller': controller,
                'ean': ean
            }
        )

    async def realtime_message(self, event):
        message = event.get('message', {})
        controller = event.get('controller', '')
        ean = event.get('ean', '')
        final_res = message.get('final_res', [])

        print(f"ВОт такой message: {message}")  # Для отладки

        not_in_db = []
        in_db = []

        # Если final_res не пустой, добавляем в in_db с сообщением
        if final_res and isinstance(final_res, list) and len(final_res) > 0:
            in_db.append({"ean": ean, "controller": controller, "message": final_res})
        else:
            not_in_db.append({"ean": ean, "controller": controller})

        await self.send(text_data=json.dumps({
            'not_in_db': not_in_db,
            'in_db': in_db
        }))


class RealDeleteConsumer(AsyncWebsocketConsumer):
    """
        Консюмер который отвечает за передачу сообщений
        с бэка на фронт в реальном времени
        для удаления товара, удалился или нет
    """
    async def connect(self):
        await self.channel_layer.group_add(
            "delete_group",
            self.channel_name
        )
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            "delete_group",
            self.channel_name
        )

    async def receive(self, text_data):
        text_data_json = json.loads(text_data)
        message = text_data_json.get("message", {})
        controller = text_data_json.get("controller", "")
        eans = text_data_json.get("eans", [])
        await self.channel_layer.group_send(
            "delete_group",
            {
                'type': 'delete_message',
                'message': message,
                'controller': controller,
                'eans': eans
            }
        )

    async def delete_message(self, event):
        message = event["message"]
        controller = event["controller"]
        ean = event["ean"]
        storefront = event["storefront"]

        print(f"Delete Message: {message}")  # Для отладки

        deleted_items = []
        failed_items = []

        if message["info"] == "Удален" or message["info"] == "Нету unit-ids":
            deleted_items.append({"ean": ean, "controller": controller, "message": message, "storefront": storefront})
        else:
            failed_items.append({"ean": ean, "controller": controller, "message": message, "storefront": storefront})

        await self.send(text_data=json.dumps({
            'deleted_items': deleted_items,
            'failed_items': failed_items
        }))


class PriceUpdateConsumer(AsyncWebsocketConsumer):
    """
        Консюмер который отвечает за передачу сообщений
        с бэка на фронт в реальном времени
        для обновления цен на товары, показываем EAN
        Старую цену и новую цену
    """

    async def connect(self):
        await self.channel_layer.group_add(
            "price_updates",
            self.channel_name
        )
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            "price_updates",
            self.channel_name
        )

    async def receive(self, text_data):
        text_data_json = json.loads(text_data)
        message = text_data_json.get("message", {})
        controller = text_data_json.get("controller", "")
        eans = text_data_json.get("eans", [])
        await self.channel_layer.group_send(
            "delete_group",
            {
                'type': 'delete_message',
                'message': message,
                'controller': controller,
                'eans': eans
            }
        )

    async def price_update(self, event):
        # Получаем сообщение от группы и шлём клиенту
        await self.send(text_data=json.dumps({
            "type": "price_changed",
            "ean": event["ean"],  # EAN товара
            "new_price": event["new_price"],  # Новая цена
            "old_price": event.get("old_price", None),  # Старая цена (опционально)
            "storefront": event.get("storefront", ""),  # Если есть витрина
            "timestamp": event["timestamp"],
            "result": event.get("result", event),
        }))