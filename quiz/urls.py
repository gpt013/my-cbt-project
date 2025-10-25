from django.urls import path
from . import views

app_name = 'quiz'

urlpatterns = [
    # /quiz/ -> 시험 목록 페이지
    path('', views.index, name='index'),

    # /quiz/1/request/ -> 1번 시험에 대한 응시 요청
    path('<int:quiz_id>/request/', views.request_quiz, name='request_quiz'),

    # /quiz/attempt/1/start/ -> 1번 응시 요청에 대한 시험 시작
    path('attempt/<int:attempt_id>/start/', views.start_quiz, name='start_quiz'),

    # /quiz/take/1/ -> 현재 진행중인 시험의 1페이지 풀기
    path('take/<int:page_number>/', views.take_quiz, name='take_quiz'),

    # /quiz/submit-page/1/ -> 1페이지의 답안 제출
    path('submit-page/<int:page_number>/', views.submit_page, name='submit_page'),

    # /quiz/submit-quiz/ -> 시험 최종 제출
    path('submit-quiz/', views.submit_quiz, name='submit_quiz'),

    # /quiz/results/ -> 최종 결과 페이지
    path('results/', views.quiz_results, name='quiz_results'),

    # /quiz/my-results/ -> 내가 응시한 시험 종류 목록
    path('my-results/', views.my_results_index, name='my_results_index'),

    # /quiz/my-results/1/ -> 1번 시험에 대한 나의 모든 결과 목록
    path('my-results/<int:quiz_id>/', views.my_results_by_quiz, name='my_results_by_quiz'),

    # /quiz/results/11/ -> 11번 시험 결과에 대한 오답노트
    path('results/<int:result_id>/', views.result_detail, name='result_detail'),

    # /quiz/upload/ -> 엑셀 문제 대량 등록 페이지
    path('upload/', views.upload_quiz, name='upload_quiz'),

    path('my-incorrect-answers/', views.my_incorrect_answers_index, name='my_incorrect_answers_index'),
    path('my-incorrect-answers/<int:quiz_id>/', views.my_incorrect_answers_by_quiz, name='my_incorrect_answers_by_quiz'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('my-dashboard/', views.personal_dashboard, name='personal_dashboard'),
    path('group-start/<int:quiz_id>/', views.start_group_quiz, name='start_group_quiz'),
    path('export-student-data/', views.export_student_data, name='export_student_data'),
    # ...
]