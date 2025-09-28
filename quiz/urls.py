# quiz/urls.py

from django.urls import path
from . import views

app_name = 'quiz'

urlpatterns = [
    # 예: /quiz/ -> 시험 목록 페이지
    path('', views.index, name='index'),
    
    # 예: /quiz/1/start/ -> 1번 시험지 시작 (랜덤 문제 생성)
    path('<int:quiz_id>/start/', views.quiz_start, name='quiz_start'),
    
    # 예: /quiz/take/1/ -> 생성된 시험의 1번 문제 풀기
    path('take/<int:question_number>/', views.take_quiz, name='take_quiz'),
    
    # 예: /quiz/submit/1/ -> 1번 문제 답안 제출
    path('submit/<int:question_number>/', views.submit_answer, name='submit_answer'),

     path('results/', views.quiz_results, name='quiz_results'),
]

