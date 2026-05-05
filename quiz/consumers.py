import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async  # ★ 수정 1: DB 전용 비동기 모듈로 교체 (렉 해결의 핵심!)
from .models import ChatRoom, ChatMessage 

class NotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        if self.scope["user"].is_authenticated:
            self.user = self.scope["user"]
            self.group_name = f'user_{self.user.id}'
            await self.channel_layer.group_add(self.group_name, self.channel_name)
            await self.accept()
        else:
            await self.close()

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def send_notification(self, event):
        message = event['message']
        await self.send(text_data=json.dumps({'type': 'system_alert', 'message': message}))

    async def chat_notification(self, event):
        await self.send(text_data=json.dumps({
            'type': 'chat_alert',
            'message': event['message'],
            'sender_name': event['sender_name'],
            'room_id': event['room_id']
        }))


class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_id = self.scope['url_route']['kwargs']['room_id']
        self.room_group_name = f'chat_{self.room_id}'

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive(self, text_data):
        text_data_json = json.loads(text_data)
        msg_type = text_data_json.get('type', 'chat_message')

        if msg_type == 'mark_read':
            did_read_new = await self.mark_messages_as_read()
            if did_read_new:
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {'type': 'broadcast_read_receipt'}
                )
        else:
            message = text_data_json.get('message', '')
            username = text_data_json.get('username', '익명')
            file_url = text_data_json.get('file_url', None)
            file_name = text_data_json.get('file_name', None)
            parent_id = text_data_json.get('parent_id', None)

            # 1. 메시지 DB 저장
            participants_to_notify, unread_count, parent_info, msg_id = await self.save_message(message, file_url, file_name, parent_id)

            # ========================================================
            # ★ [신규] 멘션 감지 및 사이트 전체 알림(🔔) 발송 로직 추가
            # ========================================================
            if message:
                import re
                mentioned_names = re.findall(r'@([가-힣a-zA-Z0-9_]+)', message)
                if mentioned_names:
                    await self.create_mention_notifications(username, mentioned_names, self.room_id)
            # ========================================================

            # 2. 방 안의 사람들에게 실시간 메시지 전송
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'chat_message',
                    'message': message,
                    'username': username,
                    'file_url': file_url,
                    'file_name': file_name,
                    'unread_count': unread_count,
                    'parent_sender': parent_info['sender'] if parent_info else None,
                    'parent_text': parent_info['text'] if parent_info else None,
                    'msg_id': msg_id, 
                }
            )

            # 3. 오프라인 유저를 위한 개인별 알림 전송
            for p_id in participants_to_notify:
                await self.channel_layer.group_send(
                    f'user_{p_id}',
                    {
                        'type': 'chat_notification',
                        'message': message,
                        'sender_name': username,
                        'room_id': self.room_id
                    }
                )

    async def chat_message(self, event):
        await self.send(text_data=json.dumps({
            'type': 'chat_message',
            'message': event['message'],
            'username': event['username'],
            'file_url': event.get('file_url'),
            'file_name': event.get('file_name'),
            'unread_count': event.get('unread_count'),
            'parent_sender': event.get('parent_sender'),
            'parent_text': event.get('parent_text'),
            'msg_id': event.get('msg_id'),
        }))

    async def broadcast_read_receipt(self, event):
        await self.send(text_data=json.dumps({
            'type': 'update_read_counts'
        }))

    @database_sync_to_async
    def save_message(self, message, file_url, file_name, parent_id=None):
        user = self.scope['user']
        if user.is_authenticated:
            room = ChatRoom.objects.get(id=self.room_id)
            room.hidden_by.clear() 

            parent_msg = None
            parent_info = None
            if parent_id:
                try:
                    parent_msg = ChatMessage.objects.get(id=parent_id)
                    parent_info = {
                        'sender': parent_msg.sender.profile.name if hasattr(parent_msg.sender, 'profile') else parent_msg.sender.username,
                        'text': parent_msg.content if parent_msg.content else f"[{parent_msg.file_name}]"
                    }
                except ChatMessage.DoesNotExist:
                    pass

            new_msg = ChatMessage.objects.create(
                room=room, sender=user, content=message, 
                file_url=file_url, file_name=file_name,
                parent=parent_msg
            )
            new_msg.read_by.add(user)

            from django.utils import timezone
            ChatRoom.objects.filter(id=self.room_id).update(last_activity=timezone.now())
            
            participants = room.participants.all()
            p_ids = list(participants.exclude(id=user.id).values_list('id', flat=True))
            
            unread_count = participants.count() - 1 
            return p_ids, unread_count, parent_info, new_msg.id
        return [], 0, None, None

    @database_sync_to_async
    def mark_messages_as_read(self):
        user = self.scope['user']
        if user.is_authenticated:
            room = ChatRoom.objects.get(id=self.room_id)
            unread_msgs = room.messages.exclude(read_by=user)
            if unread_msgs.exists():
                for msg in unread_msgs:
                    msg.read_by.add(user)
                return True 
        return False

    @database_sync_to_async
    def create_mention_notifications(self, sender_name, names_list, room_id):
        from django.contrib.auth.models import User
        from quiz.models import Notification
        from quiz.views import broadcast_realtime_notification
        
        for name in set(names_list):
            target_user = User.objects.filter(profile__name=name, is_active=True).first()
            if target_user and getattr(target_user, 'username', '') != getattr(sender_name, 'username', sender_name):
                Notification.objects.create(
                    recipient=target_user,
                    message=f"💬 [{sender_name}]님이 메신저에서 회원님을 호출했습니다.",
                    notification_type='chat_mention',
                    related_url=f"/quiz/chat/room/{room_id}/"
                )
                broadcast_realtime_notification(target_user.id)

    async def chat_message(self, event):
        await self.send(text_data=json.dumps({
            'type': 'chat_message',
            'message': event['message'],
            'username': event['username'],
            'file_url': event.get('file_url'),
            'file_name': event.get('file_name'),
            'unread_count': event.get('unread_count'),
            'parent_sender': event.get('parent_sender'),
            'parent_text': event.get('parent_text'),
            'msg_id': event.get('msg_id'), # ★ 수정 4: 프론트로 ID 전달
        }))

    # ★ 누락되어 튕기던 원인 함수 추가
    async def broadcast_read_receipt(self, event):
        await self.send(text_data=json.dumps({
            'type': 'update_read_counts'
        }))

    @database_sync_to_async # ★ 수정 5: DB 전용 비동기 데코레이터 (렉 100% 해결)
    def save_message(self, message, file_url, file_name, parent_id=None):
        user = self.scope['user']
        if user.is_authenticated:
            room = ChatRoom.objects.get(id=self.room_id)
            room.hidden_by.clear() 

            parent_msg = None
            parent_info = None
            if parent_id:
                try:
                    parent_msg = ChatMessage.objects.get(id=parent_id)
                    parent_info = {
                        'sender': parent_msg.sender.profile.name if hasattr(parent_msg.sender, 'profile') else parent_msg.sender.username,
                        'text': parent_msg.content if parent_msg.content else f"[{parent_msg.file_name}]"
                    }
                except ChatMessage.DoesNotExist:
                    pass

            new_msg = ChatMessage.objects.create(
                room=room, sender=user, content=message, 
                file_url=file_url, file_name=file_name,
                parent=parent_msg
            )
            new_msg.read_by.add(user)
            
            participants = room.participants.all()
            p_ids = list(participants.exclude(id=user.id).values_list('id', flat=True))
            
            unread_count = participants.count() - 1 
            return p_ids, unread_count, parent_info, new_msg.id # ★ 수정 6: 새 메시지 ID 리턴
        return [], 0, None, None

    @database_sync_to_async # ★ 수정 7
    def mark_messages_as_read(self):
        user = self.scope['user']
        if user.is_authenticated:
            room = ChatRoom.objects.get(id=self.room_id)
            unread_msgs = room.messages.exclude(read_by=user)
            if unread_msgs.exists():
                for msg in unread_msgs:
                    msg.read_by.add(user)
                return True 
        return False