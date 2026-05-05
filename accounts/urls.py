from django.urls import path, reverse_lazy
from . import views
from django.contrib.auth import views as auth_views
from django.views.decorators.cache import never_cache
from .views import custom_password_change
app_name = 'accounts'

urlpatterns = [
    # --- 1. 인증 및 계정 관리 ---
    
    # ★ [핵심 수정] 표준 LoginView 대신 우리가 만든 'custom_login' 사용
    # (그래야 '관리자 승인 대기' 체크와 '2차 정보 기입' 납치가 작동합니다)
    path('login/', never_cache(views.custom_login), name='login'),
    
    path('logout/', auth_views.LogoutView.as_view(
        # 로그아웃 후 다시 로그인 페이지로
        next_page='accounts:login'
    ), name='logout'),

    path('signup/', views.signup, name='signup'),
    
    # [삭제됨] 이메일 인증 관련 URL (인트라넷 환경 불가)
    # path('verify-email/', views.verify_email, name='verify_email'),
    # path('resend-code/', views.resend_code, name='resend_code'),

    path('complete-profile/', views.complete_profile, name='complete_profile'),
    path('profile/update/', views.profile_update, name='profile_update'),

    # --- 2. 유틸리티 (AJAX) ---
    path('ajax/load-part-leaders/', views.load_part_leaders, name='ajax_load_part_leaders'),

    # --- 3. 비밀번호 변경 (로그인 한 상태에서 변경) ---
    # 이 기능은 이메일 발송이 필요 없으므로 유지합니다.
    path('password_change/', custom_password_change, name='password_change'),

    path('password_change/done/', auth_views.PasswordChangeDoneView.as_view(
        template_name='accounts/password_change_done.html'
    ), name='password_change_done'),

    # --- 4. 비밀번호 초기화 (삭제됨) ---
    # [삭제 사유] 외부 이메일 발송이 불가능한 인트라넷 환경이므로 
    # '비밀번호 찾기' 기능은 제거합니다. (분실 시 관리자에게 요청)

    # --- 5. 상태 안내 페이지 ---
    path('status/counseling/', views.counseling_required, name='counseling_required'),
    path('status/dropout/', views.dropout_alert, name='dropout_alert'),
    path('status/completed/', views.completed_alert, name='completed_alert'),
    path('status/expired/', views.cohort_expired, name='cohort_expired'),
]