# quiz/apps.py
from django.apps import AppConfig

class QuizConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'quiz'
    # 앱의 대표 이름을 'CBT 시스템 관리'로 최종 설정합니다.
    verbose_name = 'CBT 시스템 관리'

    def ready(self):
        import quiz.signals