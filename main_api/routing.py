from django.urls import re_path, path
from .consumers import UploadProgressConsumer, DeleteProgressConsumer, CheckerProgressConsumer

websocket_urlpatterns = [
    path("ws/upload-progress/<str:job_id>/", UploadProgressConsumer.as_asgi()),
    path("ws/upload-progress/", UploadProgressConsumer.as_asgi()),
    path("ws/checker-progress/<str:job_id>/", CheckerProgressConsumer.as_asgi()),
    path("ws/checker-progress/", CheckerProgressConsumer.as_asgi()),
    path("ws/delete-progress/<str:job_id>/", DeleteProgressConsumer.as_asgi()),
    path("ws/delete-progress/", DeleteProgressConsumer.as_asgi()),
]
