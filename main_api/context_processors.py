from django.conf import settings

def global_settings(request):
    return {
        'WS_URL': settings.WS_URL
    }