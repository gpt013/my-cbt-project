from django.urls import path
from . import views

app_name = 'quiz'

urlpatterns = [
    # ==========================================
    # [Section 1] 교육생 전용 (Student Zone)
    # ==========================================
    path('mypage/', views.my_page, name='my_page'),
    path('', views.index, name='index'),
    
    # [신규] 교육생 기능 (면담 요청, 알림 상세)
    path('my-page/log/create/', views.student_create_counseling_log, name='student_create_counseling_log'),
    path('my-page/log/<int:log_id>/', views.student_log_detail, name='student_log_detail'),
    
    # 시험 응시 프로세스
    path('quiz/<int:quiz_id>/request/', views.request_quiz, name='request_quiz'),
    path('quiz/group-start/<int:quiz_id>/', views.start_group_quiz, name='start_group_quiz'),
    path('quiz/attempt/<int:attempt_id>/start/', views.start_quiz, name='start_quiz'),
    path('quiz/take/<int:page_number>/', views.take_quiz, name='take_quiz'),
    path('quiz/submit-page/<int:page_number>/', views.submit_page, name='submit_page'),
    path('quiz/submit-quiz/', views.submit_quiz, name='submit_quiz'),
    
    # 결과 및 오답노트
    path('quiz/results/', views.quiz_results, name='quiz_results'),
    path('quiz/my-results/', views.my_results_index, name='my_results_index'),
    path('quiz/my-results/<int:quiz_id>/', views.my_results_by_quiz, name='my_results_by_quiz'),
    path('quiz/results/<int:result_id>/', views.result_detail, name='result_detail'),
    
    path('quiz/my-incorrect-answers/', views.my_incorrect_answers_index, name='my_incorrect_answers_index'),
    path('quiz/my-incorrect-answers/<int:quiz_id>/', views.my_incorrect_answers_by_quiz, name='my_incorrect_answers_by_quiz'),
    path('quiz/personal_dashboard/', views.personal_dashboard, name='personal_dashboard'),
    path('certificate/', views.certificate_view, name='certificate_view'),

    # ==========================================
    # [Section 2] 매니저 센터 (Manager Center)
    # ==========================================
    
    # 1. 대시보드
    path('manager/', views.manager_dashboard, name='manager_dashboard'),
    
    # 2. 교육생 관리
    path('manager/trainees/', views.manager_trainee_list, name='manager_trainee_list'),
    path('manager/trainees/<int:profile_id>/', views.manager_trainee_detail, name='manager_trainee_detail'),
    
    # 3. 면담 및 평가
    path('manager/interview/<int:profile_id>/', views.manage_interviews, name='manage_interviews'),
    path('manager/log/<int:profile_id>/', views.manage_student_logs, name='manage_student_logs'),
    path('manager/log/create/<int:profile_id>/', views.manager_create_counseling_log, name='manager_create_counseling_log'),
    path('manager/evaluate/<int:profile_id>/', views.evaluate_trainee, name='evaluate_trainee'),

    # 4. 액션 (AJAX)
    path('manager/action/approve-signup/', views.approve_signup_bulk, name='approve_signup_bulk'),
    path('manager/action/reset-password/', views.reset_password_bulk, name='reset_password_bulk'),
    path('manager/action/unlock-account/<int:profile_id>/', views.unlock_account, name='unlock_account'),

    # 5. 시험 및 요청 관리
    path('manager/requests/', views.manager_exam_requests, name='manager_exam_requests'),
    path('manager/requests/approve/<int:attempt_id>/', views.approve_attempt, name='approve_attempt'),

    # 6. 퀴즈 제작 및 관리
    path('manager/quizzes/', views.manager_quiz_list, name='manager_quiz_list'),
    path('manager/quiz/create-ui/', views.quiz_create, name='quiz_create'),
    path('manager/quiz/<int:quiz_id>/update/', views.quiz_update, name='quiz_update'),
    path('manager/quiz/<int:quiz_id>/delete/', views.quiz_delete, name='quiz_delete'),
    
    # 7. 문제(Question) 관리 [하이브리드 방식 적용]
    path('manager/quiz/<int:quiz_id>/questions/', views.question_list, name='question_list'),
    path('manager/quiz/action/add-question/', views.add_question_to_quiz, name='add_question_to_quiz'),      # [신규]
    path('manager/quiz/action/remove-question/', views.remove_question_from_quiz, name='remove_question_from_quiz'), # [신규]

    path('manager/quiz/<int:quiz_id>/question/add/', views.question_create, name='question_create'),
    path('manager/question/<int:question_id>/update/', views.question_update, name='question_update'),
    path('manager/question/<int:question_id>/delete/', views.question_delete, name='question_delete'),

    # 8. 엑셀 업로드 및 다운로드
    path('manager/quiz/upload-excel/', views.upload_quiz, name='upload_quiz'),
    path('manager/quiz/bulk-sheet/', views.bulk_add_sheet_view, name='bulk_add_sheet_view'),
    path('manager/quiz/bulk-sheet/save/', views.bulk_add_sheet_save, name='bulk_add_sheet_save'),
    
    # [중요] 엑셀 다운로드 (Admin 템플릿과 이름 일치)
    path('export/student-data/', views.export_student_data, name='export_student_data'),

    # 9. 리포트 및 기타
    path('manager/report/pl/', views.pl_report_view, name='pl_report_view'),
    path('pl-dashboard/detail/<int:profile_id>/', views.pl_trainee_detail, name='pl_trainee_detail'),
    
    # [복구됨] 공정 열람 권한 요청 (기존 대시보드 호환용)
    path('request-access/', views.request_process_access, name='request_process_access'),
    path('manage-requests/', views.manage_access_requests, name='manage_access_requests'),
    path('approve-request/<int:request_id>/<str:action>/', views.approve_access_request, name='approve_access_request'),

    # (구버전 호환)
    path('quiz/dashboard/', views.dashboard, name='dashboard'),
    path('pl-dashboard/', views.pl_dashboard, name='pl_dashboard'),
    path('manager/quiz/<int:quiz_id>/manage-questions/', views.quiz_question_manager, name='quiz_question_manager'),
]