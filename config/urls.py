"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
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

