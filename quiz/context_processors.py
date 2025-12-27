# quiz/context_processors.py (새로 생성)

from .models import Notification

def notification_status(request):
    """
    모든 템플릿에서 '안 읽은 알림 여부'를 사용할 수 있게 해주는 함수
    """
    if request.user.is_authenticated:
        # 내 알림 중 '읽지 않음(is_read=False)'인 것만 카운트
        unread_count = Notification.objects.filter(recipient=request.user, is_read=False).count()
        return {
            'has_unread_notifications': unread_count > 0, # True면 빨간점 표시
            'unread_notification_count': unread_count     # (선택) 개수 표시용
        }
    return {
        'has_unread_notifications': False,
        'unread_notification_count': 0
    }