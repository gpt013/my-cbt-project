from django.urls import path
from . import views
from . import views_facility

app_name = 'quiz'

urlpatterns = [
    # ==========================================
    # [Section 1] 공통 및 학생 기능 (Student Zone)
    # ==========================================
    
    # 1. 메인 & 마이페이지
    path('', views.index, name='index'), 
    path('student/', views.my_page, name='my_page'),
    
    # 2. 알림 및 로그
    path('notifications/', views.notification_list, name='notification_list'),
    path('notifications/<int:noti_id>/read/', views.notification_read, name='notification_read'), # [주의] 아래 시설 알림과 이름 중복 가능성 있음 (확인 필요)
    path('my-page/notifications/', views.notification_list, name='my_notifications'), 
    
    path('student/log/create/', views.student_create_counseling_log, name='student_create_counseling_log'),
    path('student/log/<int:log_id>/', views.student_log_detail, name='student_log_detail'),
    
    # 3. 시험 응시 프로세스
    path('quiz/<int:quiz_id>/request/', views.request_quiz, name='request_quiz'),         
    path('quiz/group-start/<int:quiz_id>/', views.start_group_quiz, name='start_group_quiz'), 
    path('quiz/attempt/<int:attempt_id>/start/', views.start_quiz, name='start_quiz'),    
    path('quiz/take/<int:quiz_id>/', views.take_quiz, name='take_quiz'),
    path('result/<int:result_id>/', views.exam_result, name='exam_result'),             
    
    # 4. 결과 조회 및 오답 노트
    path('quiz/results/', views.quiz_results, name='quiz_results'), 
    path('quiz/my-results/', views.my_results_index, name='my_results_index'), 
    path('quiz/my-results/<int:quiz_id>/', views.my_results_by_quiz, name='my_results_by_quiz'), 
    path('results/<int:result_id>/', views.result_detail, name='result_detail'),
    
    path('quiz/my-incorrect-answers/', views.my_incorrect_answers_index, name='my_incorrect_answers_index'), 
    path('quiz/my-incorrect-answers/<int:quiz_id>/', views.my_incorrect_answers_by_quiz, name='my_incorrect_answers_by_quiz'), 
    
    path('quiz/personal_dashboard/', views.personal_dashboard, name='personal_dashboard'), 
    path('certificate/', views.certificate_view, name='certificate_view'), 


    # ==========================================
    # [Section 2] PL 전용 (Part Leader Zone)
    # ==========================================
    path('pl-dashboard/', views.pl_dashboard, name='pl_dashboard'),
    path('pl-dashboard/detail/<int:profile_id>/', views.pl_trainee_detail, name='pl_trainee_detail'),
    path('pl-dashboard/report/', views.pl_report_view, name='pl_report_view'),


    # ==========================================
    # [Section 3] 매니저 센터 (Manager Center)
    # ==========================================
    
    # 1. [핵심] 대시보드 및 권한 관리 (이름 충돌 해결!)
    # (A) 메인 센터 (요청/가입 승인 등 할일 목록)
    path('manager/', views.manager_dashboard, name='manager_dashboard'),
    
    # (B) 교육생 성적 관리 (구 'dashboard' -> 'student_dashboard'로 변경 권장)
    # 기존 코드 호환을 위해 name='dashboard'는 유지하되, 위 manager_dashboard와 겹치지 않게 주의
    path('quiz/dashboard/', views.dashboard, name='dashboard'), 
    
    path('request-access/', views.request_process_access, name='request_process_access'),
    path('manage-requests/', views.manage_access_requests, name='manage_access_requests'),
    path('approve-request/<int:request_id>/<str:action>/', views.approve_access_request, name='approve_access_request'),

    # 2. 교육생 관리
    path('manager/trainees/', views.manager_trainee_list, name='manager_trainee_list'),
    path('manager/trainees/<int:profile_id>/', views.manager_trainee_detail, name='manager_trainee_detail'),
    
    # 3. 평가 및 특이사항 관리
    path('manager/trainees/<int:profile_id>/logs/', views.manage_student_logs, name='manage_student_logs'),
    path('manager/evaluate/<int:profile_id>/', views.evaluate_trainee, name='evaluate_trainee'),       
    path('manager/log/create/<int:profile_id>/', views.manager_create_log_ajax, name='manager_create_log_ajax'),
    path('manager/interview/<int:profile_id>/', views.manage_interviews, name='manage_interviews'),   

    # 4. 계정 승인/관리
    path('manager/action/approve-signup/', views.approve_signup_bulk, name='approve_signup_bulk'),
    path('manager/action/reset-password/', views.reset_password_bulk, name='reset_password_bulk'),
    path('manager/action/unlock-account/<int:profile_id>/', views.unlock_account, name='unlock_account'),

    # 5. 시험 요청 승인 (일괄 승인 포함)
    path('manager/requests/', views.manager_exam_requests, name='manager_exam_requests'),
    path('manager/requests/approve/<int:attempt_id>/', views.approve_attempt, name='approve_attempt'),
    # ★ 일괄 승인 URL (잘 들어있음)
    path('manager/requests/bulk_approve/', views.bulk_approve_attempts, name='bulk_approve_attempts'),

    # ------------------------------------------
    # 6. 시험(Quiz) 관리
    # ------------------------------------------
    path('manager/quizzes/', views.manager_quiz_list, name='manager_quiz_list'),
    path('manager/quiz/create/', views.quiz_create, name='quiz_create'),
    path('manager/quiz/<int:quiz_id>/update/', views.quiz_update, name='quiz_update'),
    path('manager/quiz/<int:quiz_id>/delete/', views.quiz_delete, name='quiz_delete'),
    
    # ------------------------------------------
    # 7. 문제(Question) 관리
    # ------------------------------------------
    path('manager/quiz/<int:quiz_id>/questions/', views.question_list, name='question_list'),
    path('manager/quiz/<int:quiz_id>/question/add/', views.question_create, name='question_create'),
    path('manager/question/<int:question_id>/update/', views.question_update, name='question_update'),
    path('manager/question/<int:question_id>/delete/', views.question_delete, name='question_delete'),

    path('manager/quiz/<int:quiz_id>/manage-questions/', views.quiz_question_manager, name='quiz_question_manager'),
    path('manager/quiz/action/add-question/', views.add_question_to_quiz, name='add_question_to_quiz'),
    path('manager/quiz/action/remove-question/', views.remove_question_from_quiz, name='remove_question_from_quiz'),

    # 8. 엑셀 및 기타 기능
    path('manager/quiz/upload-excel/', views.upload_quiz, name='upload_quiz'),
    path('manager/quiz/bulk-sheet/', views.bulk_add_sheet_view, name='bulk_add_sheet_view'),
    path('manager/quiz/bulk-sheet/save/', views.bulk_add_sheet_save, name='bulk_add_sheet_save'),
    path('export/student-data/', views.export_student_data, name='export_student_data'),
    path('manager/quiz/bulk-upload/', views.bulk_upload_file, name='bulk_upload_file'),

    # 9. 전체 데이터 뷰
    path('manager/full-data-view/', views.admin_full_data_view, name='admin_full_data_view'),
    path('manager/report/create/<int:profile_id>/', views.manager_trainee_report, name='manager_trainee_report'),
    
    # [7번 기능] 접속 제한 안내 페이지들
    path('status/counseling/', views.counseling_required_view, name='counseling_required'), 
    path('status/dropout/', views.dropout_alert_view, name='dropout_alert'),               
    path('status/completed/', views.completed_alert_view, name='completed_alert'),         

    # 시설 예약 시스템 (views_facility 사용)
    path('manager/facility/', views_facility.facility_dashboard, name='facility_dashboard'),
    path('manager/facility/events/', views_facility.facility_events, name='facility_events'),
    path('manager/facility/reserve/', views_facility.facility_reserve, name='facility_reserve'),
    path('manager/facility/update/', views_facility.facility_update, name='facility_update'),
    path('manager/facility/action/<int:event_id>/', views_facility.facility_action, name='facility_action'),
    
    # [주의] 알림 읽음 처리가 중복됨. 기능이 같다면 아래 하나를 주석 처리하거나 이름을 바꿔야 함.
    # 기존: notification_read (Line 17) 와 아래 (Line 153) 충돌 가능성 있음.
    # path('notification/read/<int:noti_id>/', views_facility.notification_read, name='notification_read_facility'), 
    
    # 시설 관련 알림 기능 (이름 변경 추천: facility_notification_...)
    path('notification/delete/<int:noti_id>/', views_facility.notification_delete, name='notification_delete'),
    path('notification/clear-all/', views_facility.notification_clear_all, name='notification_clear_all'),
    path('api/notifications/', views_facility.notification_api_list, name='notification_api_list'),            

    # ==========================================
    # [Section 4] 새로 분리된 대시보드 (핵심 수정)
    # ==========================================
    
    # 1. 교육생 성적 관리 (Student Grades Dashboard)
    # [수정] 위쪽의 manager_dashboard와 이름이 겹치지 않게 'student_dashboard'로 명명
    path('manager/students/', views.dashboard, name='student_dashboard'), 
    
    # 상세 분석 페이지
    path('manager/student/<int:profile_id>/analysis/', views.student_analysis_detail, name='student_analysis_detail'),

    # 2. PMTC 시험 분석 센터 (Exam Analytics)
    path('manager/analytics/', views.exam_analytics_dashboard, name='exam_analytics'),
    path('manager/analytics/quiz/<int:quiz_id>/', views.question_analytics_detail, name='question_analytics_detail'),
    path('manager/analytics/quiz/<int:quiz_id>/auto_adjust/', views.auto_adjust_difficulty, name='auto_adjust_difficulty'),
    path('manager/students/excel/', views.student_dashboard_excel, name='student_dashboard_excel'),
    path('manager/access/request/', views.request_process_access, name='request_process_access'),
    path('manager/analytics/exam/<int:quiz_id>/', views.exam_analytics_detail, name='exam_analytics_detail'),
    path('manager/analytics/adjust/<int:quiz_id>/', views.auto_adjust_difficulty, name='auto_adjust_difficulty'),
    path('notification/read/<int:id>/', views_facility.read_notification, name='read_notification'),
    path('manager/dropout/request/', views.request_dropout, name='request_dropout'),
    path('admin/dropout/requests/', views.dropout_request_list, name='dropout_request_list'),
    path('admin/dropout/approve/<int:req_id>/', views.approve_dropout, name='approve_dropout'),
    path('admin/dropout/reject/<int:req_id>/', views.reject_dropout, name='reject_dropout'),
    path('manager/cohort/<int:cohort_id>/report/', views.cohort_final_report, name='cohort_final_report'),
    path('manager/report/latest/', views.latest_cohort_report, name='latest_cohort_report'),
    path('manager/cohort/<int:cohort_id>/export/', views.export_cohort_report_excel, name='export_cohort_excel'),
    path('manager/log/quick-add/', views.quick_add_warning, name='quick_add_warning'),
    
    path('status/pending/', views.status_pending, name='status_pending'),
    path('status/dropout/', views.status_dropout, name='status_dropout'),
    path('status/graduated/', views.status_graduated, name='status_graduated'),
    
    # 수료증 인쇄 API
    path('status/certificate/', views.print_certificate, name='print_certificate'),
]