# accounts/urls.py
from django.urls import path
from . import views
# Django의 내장 로그인/로그아웃 뷰를 가져옵니다.
from django.contrib.auth import views as auth_views

app_name = 'accounts'
urlpatterns = [
    path('signup/', views.signup, name='signup'),
    # --- 아래 두 줄을 추가합니다. ---
    path('login/', auth_views.LoginView.as_view(template_name='accounts/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
]