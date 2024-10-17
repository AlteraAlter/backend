from django.urls import path, include
from . import views
urlpatterns = [
    path('', views.home, name='home'),
    path('signin/', views.signin, name='signin'),
    path('signup/', views.signup, name='signup'),
    path('logout/', views.logout_, name='logout'),
    path('profile/<int:id>', views.profile, name='profile'),
    path('forgot_password', views.forgot_password, name='forgot_password'),
    path('password_reset_success', views.password_reset_success, name='password_reset_success'),
    path('password_change/<uidb64>/<token>/', views.change_password, name='password_change'),
]
