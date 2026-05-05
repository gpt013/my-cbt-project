from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/notifications/$', consumers.NotificationConsumer.as_asgi()),
    
    # ★ 수정됨: 주소 뒤에 방 번호(room_id)를 숫자로 받을 수 있게 정규표현식 적용!
    re_path(r'ws/chat/(?P<room_id>\w+)/$', consumers.ChatConsumer.as_asgi()),
]