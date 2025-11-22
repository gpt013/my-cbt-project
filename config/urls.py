"""
URL configuration for config project.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from accounts import views as accounts_views

urlpatterns = [
    # ▼▼▼ [핵심 수정] 관리자 로그아웃을 가로채서 -> 우리가 만든 로그인 페이지(accounts:login)로 보냄 ▼▼▼
    # 주의: 반드시 아래의 'path('admin/', ...)' 보다 윗줄에 적어야 작동합니다!
    path('admin/logout/', accounts_views.custom_logout, name='logout'),
    # ▲▲▲ ------------------------------------------------------------------------- ▲▲▲

    path('admin/', admin.site.urls),
    path('quiz/', include('quiz.urls')),
    path('accounts/', include('accounts.urls')),
]

# 미디어 파일(이미지 등)을 배포 환경에서 보여주기 위한 설정
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# --- [핵심] 관리자 사이트 제목 변경 ---
admin.site.site_header = "PMTC CBT 관리 사이트"  # 로그인 화면 및 상단 바
admin.site.site_title = "PMTC CBT"             # 브라우저 탭 제목
admin.site.index_title = "데이터 관리 대시보드"   # 메인 화면 제목