from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from main_api.views import MainOperationsView, index, UploadCollectionsViaJsonView, ProtectedView

urlpatterns = [
    path("kaufland_main/", MainOperationsView.as_view(), name="main_operations"),
    path("kaufland_main/upload_json/", UploadCollectionsViaJsonView.as_view(), name="upload_collections"),
    path('', index, name='index'),
    path('delete_real/', index, name='delete_real'),  # Новый маршрут для шаблона
    path('change_price/', index, name='change_price'),
    path("protected/", ProtectedView.as_view(), name='protected'),
    path('token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
]