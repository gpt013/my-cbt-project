from django.urls import path, reverse_lazy
from . import views
from django.contrib.auth import views as auth_views

app_name = 'accounts'

urlpatterns = [
    # --- 1. 인증 및 계정 관리 ---
    path('login/', auth_views.LoginView.as_view(
        template_name='accounts/login.html', 
        redirect_authenticated_user=True
    ), name='login'),
    
    path('logout/', auth_views.LogoutView.as_view(
        # [수정] 하드코딩 '/accounts/login/' 대신 URL 이름 사용 -> 유지보수에 훨씬 유리함
        next_page='accounts:login'
    ), name='logout'),

    path('signup/', views.signup, name='signup'),
    path('complete-profile/', views.complete_profile, name='complete_profile'),

    # --- 2. 유틸리티 (AJAX) ---
    path('ajax/load-part-leaders/', views.load_part_leaders, name='ajax_load_part_leaders'),

    # --- 3. 비밀번호 변경 (로그인 후 변경 / 강제 변경 납치용) ---
    path('password_change/', auth_views.PasswordChangeView.as_view(
        template_name='accounts/password_change_form.html', 
        # [수정] reverse_lazy를 사용하여 URL이 변경되어도 자동 적용되게 함
        success_url=reverse_lazy('accounts:password_change_done')
    ), name='password_change'),

    path('password_change/done/', auth_views.PasswordChangeDoneView.as_view(
        template_name='accounts/password_change_done.html'
    ), name='password_change_done'),

    # --- 4. 비밀번호 초기화 (로그인 못할 때 이메일로 찾기) ---
    
    # (1) 이메일 입력 요청
    path('password_reset/', auth_views.PasswordResetView.as_view(
        template_name='accounts/password_reset_form.html',
        email_template_name='accounts/password_reset_email.html',
        subject_template_name='accounts/password_reset_subject.txt',
        success_url=reverse_lazy('accounts:password_reset_done')
    ), name='password_reset'),

    # (2) 메일 발송 완료 안내
    path('password_reset/done/', auth_views.PasswordResetDoneView.as_view(
        template_name='accounts/password_reset_done.html'
    ), name='password_reset_done'),

    # (3) 메일 링크 클릭 후 새 비밀번호 입력
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='accounts/password_reset_confirm.html',
        success_url=reverse_lazy('accounts:password_reset_complete')
    ), name='password_reset_confirm'),

    # (4) 초기화 완료 안내
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(
        template_name='accounts/password_reset_complete.html'
    ), name='password_reset_complete'),
]