from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from main_api.views import (
    MainOperationsView,
    UploadCollectionsViaJsonView,
    ProtectedView,
    HealthCheckView,
    ProductByEanView,
    StopJobView,
    AftercoolLoginView
)
from main_api.auth.views import CustomTokenObtainSlidingView

urlpatterns = [
    path("health/", HealthCheckView.as_view(), name="health"),
    path("products/ean/<str:ean>/", ProductByEanView.as_view(), name="product_by_ean"),
    path("kaufland_main/", MainOperationsView.as_view(), name="main_operations"),
    path(
        "kaufland_main/upload_json/",
        UploadCollectionsViaJsonView.as_view(),
        name="upload_collections",
    ),
    path("kaufland_main/stop_job/", StopJobView.as_view(), name="stop_job"),
    path("protected/", ProtectedView.as_view(), name="protected"),
    path("token/", CustomTokenObtainSlidingView.as_view(), name="token_obtain_pair"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("aftercool_login/", AftercoolLoginView.as_view(), name="aftercool_login"),
]
