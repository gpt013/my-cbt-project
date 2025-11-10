from django.urls import path
from . import views

app_name = 'quiz'

urlpatterns = [
    # --- 1. '마이 페이지' (로그인 후 첫 화면) ---
    path('mypage/', views.my_page, name='my_page'),
    
    # --- 2. '시험 목록' ---
    path('', views.index, name='index'),
    
    # --- 3. 시험 응시/시작 로직 ---
    path('quiz/<int:quiz_id>/request/', views.request_quiz, name='request_quiz'),
    path('quiz/group-start/<int:quiz_id>/', views.start_group_quiz, name='start_group_quiz'),
    path('quiz/attempt/<int:attempt_id>/start/', views.start_quiz, name='start_quiz'),
    
    # --- 4. 시험 진행 ---
    path('quiz/take/<int:page_number>/', views.take_quiz, name='take_quiz'),
    path('quiz/submit-page/<int:page_number>/', views.submit_page, name='submit_page'),
    path('quiz/submit-quiz/', views.submit_quiz, name='submit_quiz'),
    
    # --- 5. 결과 및 오답노트 ---
    path('quiz/results/', views.quiz_results, name='quiz_results'),
    path('quiz/my-results/', views.my_results_index, name='my_results_index'),
    path('quiz/my-results/<int:quiz_id>/', views.my_results_by_quiz, name='my_results_by_quiz'),
    path('quiz/results/<int:result_id>/', views.result_detail, name='result_detail'),
    
    # --- 6. 누적 오답노트 ---
    path('quiz/my-incorrect-answers/', views.my_incorrect_answers_index, name='my_incorrect_answers_index'),
    path('quiz/my-incorrect-answers/<int:quiz_id>/', views.my_incorrect_answers_by_quiz, name='my_incorrect_answers_by_quiz'),
    
    # --- 7. 대시보드 ---
    path('quiz/dashboard/', views.dashboard, name='dashboard'),
    path('quiz/personal_dashboard/', views.personal_dashboard, name='personal_dashboard'),
    
    # --- 8. 엑셀 기능 (현재 비활성화) ---
    path('quiz/export-student-data/', views.export_student_data, name='export_student_data'),
    path('quiz/upload/', views.upload_quiz, name='upload_quiz'),
]