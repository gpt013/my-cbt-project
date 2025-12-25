from django.urls import path
from . import views

app_name = 'attendance'

urlpatterns = [
    # 1. 메인 화면 (스마트 출근 인증) - 기존 mdm_status가 index.html을 보여주게 연결됨
    path('', views.mdm_status, name='mdm_status'), 
    
    # 2. [신규] 출근 처리 (AJAX)
    path('process/', views.process_attendance, name='process_attendance'),

    # 3. 근무표 및 기타 기능
    path('schedule/', views.schedule_index, name='schedule_index'),
    path('schedule/update/', views.update_schedule, name='update_schedule'),
    path('schedule/requests/', views.get_pending_requests, name='get_pending_requests'),
    path('schedule/process/', views.process_request, name='process_request'),
    path('schedule/apply-all/', views.apply_all_normal, name='apply_all_normal'),
    path('check-in/', views.check_in_page, name='check_in_page'), # 출근 페이지
    path('api/check-in/', views.check_in_api, name='check_in_api'), # 실제 처리(AJAX)
    path('request/<int:request_id>/<str:action>/', views.process_request, name='process_request'),
    
]