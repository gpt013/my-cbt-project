# accounts/apps.py
from django.apps import AppConfig

class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'accounts'
    # 앱의 대표 이름을 '교육생 관리'로 최종 설정합니다.
    verbose_name = '교육생 관리'

    def ready(self):
        import accounts.signals