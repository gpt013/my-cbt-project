# quiz/routing.py
from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    # ws/notifications/ 주소로 WebSocket 연결 요청이 오면 NotificationConsumer를 연결합니다.
    re_path(r'ws/notifications/$', consumers.NotificationConsumer.as_asgi()),
]