from django.urls import re_path, path
from .consumers import UploadProgressConsumer

websocket_urlpatterns = [
    path("ws/upload-progress/", UploadProgressConsumer.as_asgi()),
]
