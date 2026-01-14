import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
import main_api.routing

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'kaufland_API.settings')

django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter({
    'http': django_asgi_app,
    'websocket': URLRouter(main_api.routing.websocket_urlpatterns),
})