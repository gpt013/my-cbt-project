from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from .models import Choice, Question, Quiz # Quiz를 import 했는지 확인
import random # 랜덤 선택을 위해 추가합니다.

# 'index'라는 이름의 주방(View)을 만듭니다.
def index(request):
    # 모든 Question 대신 모든 Quiz를 가져옵니다.
    quiz_list = Quiz.objects.all()
    # 'quiz_list' 라는 이름으로 데이터를 담습니다.
    context = {'quiz_list': quiz_list}
    # 'quiz/index.html'에 전달합니다. (템플릿 이름은 그대로 사용)
    return render(request, 'quiz/index.html', context)


def quiz_start(request, quiz_id):
    """시험을 시작하는 함수 (부족한 문제는 다른 난이도에서 채우는 방식)"""
    quiz = get_object_or_404(Quiz, pk=quiz_id)

    # --- 1. 이 시험지에 속한 모든 문제를 난이도별로 미리 준비합니다. ---
    questions_hard = list(quiz.question_set.filter(difficulty='상'))
    questions_medium = list(quiz.question_set.filter(difficulty='중'))
    questions_easy = list(quiz.question_set.filter(difficulty='하'))

    # --- 2. 목표 수량만큼 우선적으로 랜덤 선택합니다. ---
    # 문제가 부족하면 있는 만큼만 선택됩니다.
    selected_hard = random.sample(questions_hard, min(len(questions_hard), 8))
    selected_medium = random.sample(questions_medium, min(len(questions_medium), 9))
    selected_easy = random.sample(questions_easy, min(len(questions_easy), 8))

    # --- 3. 우선 선택된 문제들과 부족한 문제 수를 계산합니다. ---
    initial_selection = selected_hard + selected_medium + selected_easy
    shortfall = 25 - len(initial_selection)

    # --- 4. 부족한 문제가 있다면, 나머지 문제들로 채워넣습니다. ---
    if shortfall > 0:
        # 전체 문제 목록에서 이미 선택된 문제들을 제외한 나머지 문제들을 준비합니다.
        all_questions = questions_hard + questions_medium + questions_easy
        remaining_pool = [q for q in all_questions if q not in initial_selection]

        # 부족한 수량만큼 나머지 문제들 중에서 랜덤으로 추가 선택합니다.
        fill_in_questions = random.sample(remaining_pool, min(len(remaining_pool), shortfall))
        final_questions = initial_selection + fill_in_questions
    else:
        final_questions = initial_selection

    # --- 5. 최종 문제 목록의 순서를 섞고 세션에 저장합니다. ---
    random.shuffle(final_questions)

    request.session['quiz_questions'] = [q.id for q in final_questions]
    request.session['user_answers'] = {}

    # 첫 번째 문제 페이지로 이동
    return HttpResponseRedirect(reverse('quiz:take_quiz', args=(1,)))

def take_quiz(request, question_number):
    """문제를 푸는 함수"""
    # 세션에서 문제 ID 목록을 가져옵니다.
    question_ids = request.session.get('quiz_questions')
    if not question_ids or question_number > len(question_ids):
        # 세션에 문제가 없거나 마지막 문제를 넘어가면, 목록 페이지로 보냅니다.
        return HttpResponseRedirect(reverse('quiz:index'))

    # 현재 문제 번호에 해당하는 문제 ID를 찾아서 문제를 가져옵니다.
    question_id = question_ids[question_number - 1]
    question = get_object_or_404(Question, pk=question_id)
    
    context = {
        'question': question,
        'question_number': question_number,
        'total_questions': len(question_ids)
    }
    return render(request, 'quiz/take_quiz.html', context)

def submit_answer(request, question_number):
    """답안을 제출하고 다음 문제로 넘어가는 함수"""
    question_ids = request.session.get('quiz_questions')
    question_id = question_ids[question_number - 1]
    
    try:
        selected_choice_id = request.POST['choice']
    except (KeyError, Choice.DoesNotExist):
        # 보기를 선택하지 않았다면 다시 현재 문제 페이지로 보냅니다.
        question = get_object_or_404(Question, pk=question_id)
        context = {
            'question': question,
            'question_number': question_number,
            'total_questions': len(question_ids),
            'error_message': "보기를 선택해주세요."
        }
        return render(request, 'quiz/take_quiz.html', context)

    # 사용자의 답을 세션에 저장합니다.
    user_answers = request.session['user_answers']
    user_answers[str(question_id)] = int(selected_choice_id)
    request.session['user_answers'] = user_answers

    if question_number < len(question_ids):
        # 다음 문제가 있다면, 다음 문제 페이지로 이동합니다.
        return HttpResponseRedirect(reverse('quiz:take_quiz', args=(question_number + 1,)))
    else:
        # 마지막 문제라면, 결과 페이지로 이동합니다. (결과 페이지는 다음 단계에서 만듭니다)
         return HttpResponseRedirect(reverse('quiz:quiz_results'))# 임시로 목록 페이지로 이동
    
def quiz_results(request):
    """채점 및 최종 결과 페이지를 보여주는 함수"""
    question_ids = request.session.get('quiz_questions', [])
    user_answers = request.session.get('user_answers', {})

    # ID를 이용해 전체 Question 객체들을 한번에 불러옵니다.
    questions = Question.objects.filter(pk__in=question_ids)

    score = 0
    results_data = []

    for question in questions:
        question_id_str = str(question.id)
        user_choice_id = user_answers.get(question_id_str)
        
        correct_choice = question.choice_set.get(is_correct=True)
        is_correct = (user_choice_id == correct_choice.id)

        if is_correct:
            score += 1
        
        results_data.append({
            'question': question,
            'user_choice_id': user_choice_id,
            'correct_choice_id': correct_choice.id,
            'is_correct': is_correct
        })
    
    total_questions = len(question_ids)
    
    context = {
        'results_data': results_data,
        'score': score,
        'total_questions': total_questions
    }

    # 시험이 끝나면 세션 데이터를 정리합니다.
    request.session.pop('quiz_questions', None)
    request.session.pop('user_answers', None)

    return render(request, 'quiz/quiz_results.html', context)