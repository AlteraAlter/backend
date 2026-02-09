import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from channels.security.websocket import OriginValidator
from django.conf import settings
import main_api.routing

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "kaufland_API.settings")

django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": OriginValidator(
            AuthMiddlewareStack(
                URLRouter(main_api.routing.websocket_urlpatterns),
            ),
            allowed_origins=getattr(settings, "CORS_ALLOWED_ORIGINS", []),
        ),
    }
)
