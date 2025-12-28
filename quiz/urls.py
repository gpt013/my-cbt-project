from django.urls import path
from . import views

app_name = 'quiz'

urlpatterns = [
    # ==========================================
    # [Section 1] 공통 및 학생 기능 (Student Zone)
    # ==========================================
    
    # 1. 메인 & 마이페이지
    path('', views.index, name='index'), # 교육생 센터 홈 (시험 목록)
    path('student/', views.my_page, name='my_page'), # 마이페이지
    
    # 2. 알림 및 로그 (학생용)
    path('notifications/', views.notification_list, name='notification_list'),
    path('notifications/<int:noti_id>/read/', views.notification_read, name='notification_read'),
    
    # [수정 완료] 템플릿 오류 해결을 위해 'my_notifications' 이름 복구
    path('my-page/notifications/', views.notification_list, name='my_notifications'), 
    
    # 학생이 상담 요청(로그 생성)
    path('student/log/create/', views.student_create_counseling_log, name='student_create_counseling_log'),
    path('student/log/<int:log_id>/', views.student_log_detail, name='student_log_detail'),
    
    # 3. 시험 응시 프로세스
    path('quiz/<int:quiz_id>/request/', views.request_quiz, name='request_quiz'),         
    path('quiz/group-start/<int:quiz_id>/', views.start_group_quiz, name='start_group_quiz'), 
    path('quiz/attempt/<int:attempt_id>/start/', views.start_quiz, name='start_quiz'),    
    path('quiz/take/<int:page_number>/', views.take_quiz, name='take_quiz'),             
    path('quiz/submit-page/<int:page_number>/', views.submit_page, name='submit_page'),   
    path('quiz/submit-quiz/', views.submit_quiz, name='submit_quiz'),                     
    
    # 4. 결과 및 오답 노트
    path('quiz/results/', views.quiz_results, name='quiz_results'), 
    path('quiz/my-results/', views.my_results_index, name='my_results_index'), 
    path('quiz/my-results/<int:quiz_id>/', views.my_results_by_quiz, name='my_results_by_quiz'), 
    path('quiz/results/<int:result_id>/', views.result_detail, name='result_detail'), 
    
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
    
    # 1. 대시보드 및 권한 관리
    path('manager/', views.manager_dashboard, name='manager_dashboard'),
    path('quiz/dashboard/', views.dashboard, name='dashboard'), 
    path('request-access/', views.request_process_access, name='request_process_access'),
    path('manage-requests/', views.manage_access_requests, name='manage_access_requests'),
    path('approve-request/<int:request_id>/<str:action>/', views.approve_access_request, name='approve_access_request'),

    # 2. 교육생 관리
    path('manager/trainees/', views.manager_trainee_list, name='manager_trainee_list'),
    path('manager/trainees/<int:profile_id>/', views.manager_trainee_detail, name='manager_trainee_detail'),
    
    # 3. 평가 및 특이사항 관리
    path('manager/trainees/<int:profile_id>/logs/', views.manage_student_logs, name='manage_student_logs'),
    path('manage/student/<int:profile_id>/logs/', views.manage_student_logs), 
    
    path('manager/evaluate/<int:profile_id>/', views.evaluate_trainee, name='evaluate_trainee'),       
    path('manager/log/create/<int:profile_id>/', views.manager_create_counseling_log, name='manager_create_counseling_log'), 
    path('manager/interview/<int:profile_id>/', views.manage_interviews, name='manage_interviews'),   

    # 4. 계정 승인/관리
    path('manager/action/approve-signup/', views.approve_signup_bulk, name='approve_signup_bulk'),
    path('manager/action/reset-password/', views.reset_password_bulk, name='reset_password_bulk'),
    path('manager/action/unlock-account/<int:profile_id>/', views.unlock_account, name='unlock_account'),

    # 5. 시험 요청 승인
    path('manager/requests/', views.manager_exam_requests, name='manager_exam_requests'),
    path('manager/requests/approve/<int:attempt_id>/', views.approve_attempt, name='approve_attempt'),

    # 6. 시험(Quiz) 관리
    path('manager/quizzes/', views.manager_quiz_list, name='manager_quiz_list'),
    path('manager/quiz/create-ui/', views.quiz_create, name='quiz_create'),
    path('manager/quiz/<int:quiz_id>/update/', views.quiz_update, name='quiz_update'),
    path('manager/quiz/<int:quiz_id>/delete/', views.quiz_delete, name='quiz_delete'),
    
    # 7. 문제(Question) 관리
    path('manager/quiz/<int:quiz_id>/questions/', views.question_list, name='question_list'),
    path('manager/quiz/<int:quiz_id>/question/add/', views.question_create, name='question_create'),
    path('manager/quiz/<int:quiz_id>/manage-questions/', views.quiz_question_manager, name='quiz_question_manager'),
    
    path('manager/quiz/action/add-question/', views.add_question_to_quiz, name='add_question_to_quiz'),
    path('manager/quiz/action/remove-question/', views.remove_question_from_quiz, name='remove_question_from_quiz'),

    path('manager/question/<int:question_id>/update/', views.question_update, name='question_update'),
    path('manager/question/<int:question_id>/delete/', views.question_delete, name='question_delete'),

    # 8. 엑셀 업로드/다운로드
    path('manager/quiz/upload-excel/', views.upload_quiz, name='upload_quiz'),
    path('manager/quiz/bulk-sheet/', views.bulk_add_sheet_view, name='bulk_add_sheet_view'),
    path('manager/quiz/bulk-sheet/save/', views.bulk_add_sheet_save, name='bulk_add_sheet_save'),
    path('export/student-data/', views.export_student_data, name='export_student_data'),
    
    # 9. 전체 데이터 뷰
    path('manager/full-data-view/', views.admin_full_data_view, name='admin_full_data_view'),
]