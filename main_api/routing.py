from django.urls import re_path, path
from .consumers import UploadProgressConsumer, DeleteProgressConsumer

websocket_urlpatterns = [
    path("ws/upload-progress/", UploadProgressConsumer.as_asgi()),
    path("ws/delete-progress/", DeleteProgressConsumer.as_asgi()),
]
