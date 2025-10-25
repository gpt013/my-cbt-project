# quiz/consumers.py
import json
from channels.generic.websocket import AsyncWebsocketConsumer

class NotificationConsumer(AsyncWebsocketConsumer):
    # WebSocket 연결이 처음 맺어질 때 실행됩니다.
    async def connect(self):
        # 로그인한 사용자만 연결을 허용합니다.
        if self.scope["user"].is_authenticated:
            self.user = self.scope["user"]
            self.group_name = f'user_{self.user.id}'

            # 사용자의 고유 채널 그룹에 참여합니다.
            await self.channel_layer.group_add(
                self.group_name,
                self.channel_name
            )
            await self.accept()
        else:
            await self.close()

    # WebSocket 연결이 끊어졌을 때 실행됩니다.
    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name
            )

    # 채널 그룹으로부터 메시지를 받았을 때 실행됩니다.
    async def send_notification(self, event):
        message = event['message']
        # 받은 메시지를 WebSocket을 통해 클라이언트(브라우저)에게 전송합니다.
        await self.send(text_data=json.dumps({
            'message': message
        }))