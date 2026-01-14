from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/realtime/$', consumers.RealTimeConsumer.as_asgi()),
    re_path(r'ws/real-delete/$', consumers.RealDeleteConsumer.as_asgi()),
    re_path(r'ws/price-updates/$', consumers.PriceUpdateConsumer.as_asgi()),
]