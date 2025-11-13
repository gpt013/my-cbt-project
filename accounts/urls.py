from django.urls import path
from . import views
from django.contrib.auth import views as auth_views

app_name = 'accounts'
urlpatterns = [
    path('ajax/load-part-leaders/', views.load_part_leaders, name='ajax_load_part_leaders'),
    path('signup/', views.signup, name='signup'),
    
    # --- [핵심 추가] 프로필 완성 URL ---
    path('complete-profile/', views.complete_profile, name='complete_profile'),
    # --------------------------------

    path('login/', auth_views.LoginView.as_view(
        template_name='accounts/login.html', 
        redirect_authenticated_user=True
    ), name='login'),
    
    path('logout/', auth_views.LogoutView.as_view(
        next_page='/accounts/login/'
    ), name='logout'),

    # --- 비밀번호 재설정 기능 URL 4개 ---
    
    # 1. 비밀번호 재설정 요청 페이지 (이메일 입력)
    path('password_reset/', 
         auth_views.PasswordResetView.as_view(
             template_name='accounts/password_reset_form.html',
             email_template_name='accounts/password_reset_email.html',
             subject_template_name='accounts/password_reset_subject.txt',
             success_url='/accounts/password_reset/done/'
         ), 
         name='password_reset'),

    # 2. 이메일 발송 완료 페이지
    path('password_reset/done/', 
         auth_views.PasswordResetDoneView.as_view(
             template_name='accounts/password_reset_done.html'
         ), 
         name='password_reset_done'),

    # 3. 이메일의 링크를 클릭하면 나오는, 새 비밀번호 입력 페이지
    path('reset/<uidb64>/<token>/', 
         auth_views.PasswordResetConfirmView.as_view(
             template_name='accounts/password_reset_confirm.html',
             success_url='/accounts/reset/done/'
         ), 
         name='password_reset_confirm'),

    # 4. 비밀번호 변경 완료 페이지
    path('reset/done/', 
         auth_views.PasswordResetCompleteView.as_view(
             template_name='accounts/password_reset_complete.html'
         ), 
         name='password_reset_complete'),
    # ------------------------------------------
]