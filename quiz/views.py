# quiz/views.py 전체 코드
import pandas as pd
from django.utils import timezone
from datetime import timedelta
from django.contrib import messages # 메시지 기능을 위해 추가
from django.core.paginator import Paginator
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.db.models import Count, Avg # 데이터 집계를 위해 추가
from django.contrib.auth.models import User # User 모델을 가져옵니다.
from django.views.decorators.cache import cache_control
from django.db.models import Avg, Max # Max를 추가로 import 합니다.
import random
from accounts.models import Profile, Badge, EvaluationRecord # Profile을 가져옵니다.
# --- '로그인 필수' 기능을 가져옵니다. ---
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.core.mail import send_mail

from .models import Choice, Question, Quiz, TestResult, UserAnswer, QuizAttempt, ExamSheet, Tag

# 1. '마이 페이지' (로그인 후 첫 화면)
@login_required
def my_page(request):
    user = request.user
    
    pending_attempts = QuizAttempt.objects.filter(
        user=user, 
        status__in=['대기중', '승인됨']
    )
    latest_results = TestResult.objects.filter(user=user).order_by('-completed_at')[:3]
    
    profile, created = Profile.objects.get_or_create(user=user)
    
    latest_badges = profile.badges.all().order_by('-id')[:3]
    latest_evaluations = EvaluationRecord.objects.filter(profile=profile).order_by('-created_at')[:3]
    
    context = {
        'pending_attempts': pending_attempts,
        'latest_results': latest_results,
        'latest_badges': latest_badges,
        'latest_evaluations': latest_evaluations,
    }
    return render(request, 'quiz/my_page.html', context)

@login_required
def index(request):
    user = request.user
    user_groups = user.groups.all()
    
    user_process = None
    if hasattr(user, 'profile'):
        user_process = user.profile.process

    all_common_quizzes = Quiz.objects.filter(category=Quiz.Category.COMMON)
    
    # [1] 공통 시험 '합격' 여부 확인
    all_common_passed = False
    passed_common_count = TestResult.objects.filter(
        user=user, 
        quiz__in=all_common_quizzes, 
        is_pass=True
    ).values('quiz').distinct().count()
    if all_common_quizzes.count() > 0 and passed_common_count >= all_common_quizzes.count():
        all_common_passed = True
    elif all_common_quizzes.count() == 0:
        all_common_passed = True

    # [2] '나의 공정' 퀴즈 목록
    my_process_quizzes_list = Quiz.objects.none()
    if user_process:
        my_process_quizzes_list = Quiz.objects.filter(category=Quiz.Category.PROCESS, associated_process=user_process)
    
    # [3] '나의 공정' 시험 '합격' 여부 확인
    all_my_process_passed = False
    passed_my_process_count = TestResult.objects.filter(
        user=user, 
        quiz__in=my_process_quizzes_list, 
        is_pass=True
    ).values('quiz').distinct().count()
    if my_process_quizzes_list.count() > 0 and passed_my_process_count >= my_process_quizzes_list.count():
        all_my_process_passed = True
    elif my_process_quizzes_list.count() == 0:
        all_my_process_passed = True # 내 공정 시험이 없으면 항상 통과

    # [4] '기타 공정' 퀴즈 목록
    other_process_quizzes_list = Quiz.objects.none()
    if user_process:
        other_process_quizzes_list = Quiz.objects.filter(category=Quiz.Category.PROCESS).exclude(associated_process=user_process)
    else:
        other_process_quizzes_list = Quiz.objects.filter(category=Quiz.Category.PROCESS)

    # [5] 헬퍼 함수 (각 퀴즈의 버튼 상태 결정)
    def process_quiz_list(quiz_list):
        for quiz in quiz_list:
            quiz.user_status = None
            quiz.action_id = None
            
            latest_result = TestResult.objects.filter(user=user, quiz=quiz).order_by('-completed_at').first()
            active_individual_attempt = QuizAttempt.objects.filter(
                user=user, quiz=quiz, 
                assignment_type=QuizAttempt.AssignmentType.INDIVIDUAL,
                status__in=['대기중', '승인됨'],
                testresult__isnull=True
            ).first()

            if active_individual_attempt:
                quiz.user_status = active_individual_attempt.status
                quiz.action_id = active_individual_attempt.id
                continue

            is_group_assigned = quiz.allowed_groups.filter(id__in=user_groups).exists()
            if is_group_assigned:
                completed_group_attempt = TestResult.objects.filter(
                    user=user, quiz=quiz, 
                    attempt__assignment_type=QuizAttempt.AssignmentType.GROUP
                ).exists()
                if not completed_group_attempt:
                    quiz.user_status = '그룹 응시 가능'
                    quiz.action_id = quiz.id
                    continue
            
            if latest_result:
                quiz.user_status = '완료됨'
                quiz.action_id = latest_result.id
                quiz.is_pass = latest_result.is_pass
                continue
                
            quiz.user_status = '요청 가능'
            quiz.action_id = quiz.id
        return quiz_list

    common_quizzes = process_quiz_list(all_common_quizzes)
    my_process_quizzes = process_quiz_list(my_process_quizzes_list)
    other_process_quizzes = process_quiz_list(other_process_quizzes_list)

    # --- [핵심] '관리자 우선 승인'이 있는지 확인 ---
    # '나의 공정' 퀴즈 중에 '승인됨' 또는 '대기중' 상태인 것이 하나라도 있는지 확인
    my_process_has_override = any(quiz.user_status in ['승인됨', '대기중'] for quiz in my_process_quizzes)
    # '기타 공정' 퀴즈 중에 '승인됨' 또는 '대기중' 상태인 것이 하나라도 있는지 확인
    other_process_has_override = any(quiz.user_status in ['승인됨', '대기중'] for quiz in other_process_quizzes)
    # ----------------------------------------

    context = {
        'common_quizzes': common_quizzes,
        'my_process_quizzes': my_process_quizzes,
        'other_process_quizzes': other_process_quizzes,
        'all_common_passed': all_common_passed,
        'all_my_process_passed': all_my_process_passed,
        'my_process_has_override': my_process_has_override, # 템플릿으로 전달
        'other_process_has_override': other_process_has_override, # 템플릿으로 전달
    }
    return render(request, 'quiz/index.html', context)

@login_required
def my_page(request):
    user = request.user
    
    pending_attempts = QuizAttempt.objects.filter(
        user=user, 
        status__in=['대기중', '승인됨']
    )
    latest_results = TestResult.objects.filter(user=user).order_by('-completed_at')[:3]
    
    profile, created = Profile.objects.get_or_create(user=user)
    
    latest_badges = profile.badges.all().order_by('-id')[:3]
    latest_evaluations = EvaluationRecord.objects.filter(profile=profile).order_by('-created_at')[:3]
    
    context = {
        'pending_attempts': pending_attempts,
        'latest_results': latest_results,
        'latest_badges': latest_badges,
        'latest_evaluations': latest_evaluations,
    }
    return render(request, 'quiz/my_page.html', context)

@login_required
def request_quiz(request, quiz_id):
    quiz = get_object_or_404(Quiz, pk=quiz_id)

    # 이미 대기중이거나 승인된 요청이 있는지 확인
    existing_attempt = QuizAttempt.objects.filter(
        user=request.user, 
        quiz=quiz, 
        status__in=['대기중', '승인됨']
    ).first()

    if existing_attempt:
        messages.info(request, f"이미 '{quiz.title}' 시험에 대한 요청이 '{existing_attempt.status}' 상태입니다.")
    else:
        QuizAttempt.objects.create(
            user=request.user, 
            quiz=quiz, 
            assignment_type=QuizAttempt.AssignmentType.INDIVIDUAL
        )
        messages.success(request, f"'{quiz.title}' 시험 응시를 요청했습니다. 관리자의 승인을 기다려 주세요.")
    return redirect('quiz:index')

# quiz/views.py

@login_required
@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def take_quiz(request, page_number):
    question_ids = request.session.get('quiz_questions')
    attempt_id = request.session.get('attempt_id')

    # --- [핵심 보안 강화] ---
    # 세션에 attempt_id가 없으면, 비정상 접근으로 간주하고 첫 페이지로 보냅니다.
    if not attempt_id:
        messages.error(request, "잘못된 접근입니다. 시험을 다시 시작해주세요.")
        return redirect('quiz:index')

    attempt = get_object_or_404(QuizAttempt, pk=attempt_id)

    # 시험이 완료되었는지 확인하고, 완료되었다면 결과 페이지로 보냅니다.
    if attempt.status == '완료됨':
        messages.info(request, "이미 완료된 시험입니다. 결과 페이지로 이동합니다.")
        result = attempt.testresult_set.first() 
        if result:
            return redirect('quiz:result_detail', result_id=result.id)
        else:
            return redirect('quiz:my_results_index')
    # ----------------------------------------------

    if not question_ids:
        return redirect('quiz:index')

    paginator = Paginator(question_ids, 10)
    page_obj = paginator.get_page(page_number)
    questions = Question.objects.filter(pk__in=page_obj.object_list)

    user_answers = request.session.get('user_answers', {})
    for q in questions:
        choices = list(q.choice_set.all())
        random.shuffle(choices)
        q.shuffled_choices = choices
        q.previous_choice_id = user_answers.get(str(q.id))

    context = {
        'page_obj': page_obj,
        'questions': questions,
        'attempt': attempt,
        'is_in_test_mode': True, # <-- [핵심 추가] "시험 중"이라는 신호를 보냅니다.
    }
    return render(request, 'quiz/take_quiz.html', context)

@login_required
def submit_page(request, page_number):
    # --- [핵심 보안 강화] ---
    attempt_id = request.session.get('attempt_id')
    # 세션에 attempt_id가 없거나, 이미 완료된 시험이면 접근을 차단합니다.
    if not attempt_id:
        messages.error(request, "유효하지 않은 시험 접근입니다.")
        return redirect('quiz:index')

    attempt = get_object_or_404(QuizAttempt, pk=attempt_id)
    if attempt.status == '완료됨':
        messages.info(request, "이미 완료된 시험입니다.")
        result = attempt.testresult_set.first()
        return redirect('quiz:result_detail', result_id=result.id) if result else redirect('quiz:my_results_index')
    # --- 보안 강화 끝 ---

    question_ids = request.session.get('quiz_questions')
    paginator = Paginator(question_ids, 10)
    page_obj = paginator.get_page(page_number)
    current_question_ids = page_obj.object_list
    questions = Question.objects.filter(pk__in=current_question_ids)

    user_answers = request.session.get('user_answers', {})

    for question in questions:
        q_id_str = str(question.id)
        if question.question_type == '객관식':
            choice_id = request.POST.get(f'choice_{question.id}')
            if choice_id:
                user_answers[q_id_str] = int(choice_id)
        elif question.question_type == '다중선택':
            choice_ids = request.POST.getlist(f'choice_{question.id}')
            if choice_ids:
                user_answers[q_id_str] = [int(cid) for cid in choice_ids]
        elif question.question_type == '주관식':
            answer_text = request.POST.get(f'short_answer_{question.id}')
            if answer_text is not None:
                user_answers[q_id_str] = answer_text

    request.session['user_answers'] = user_answers

    if 'final_submit' in request.POST:
        return redirect('quiz:submit_quiz')
    elif 'previous' in request.POST and page_obj.has_previous():
        return redirect('quiz:take_quiz', page_number=page_obj.previous_page_number())
    elif 'next' in request.POST and page_obj.has_next():
        return redirect('quiz:take_quiz', page_number=page_obj.next_page_number())
    else:
        return redirect('quiz:take_quiz', page_number=page_obj.number)

@login_required
def quiz_results(request):
    # 세션에서 현재 진행중인 시험 정보를 가져옵니다.
    question_ids = request.session.get('quiz_questions', [])
    user_answers = request.session.get('user_answers', {})
    attempt_id = request.session.get('attempt_id')
    attempt = QuizAttempt.objects.get(pk=attempt_id) if attempt_id else None

    # 푼 문제가 없으면 메인으로 보냅니다.
    if not question_ids:
        messages.error(request, "채점할 시험 정보가 없습니다.")
        return redirect('quiz:index')

    # 1. 채점 전, 사용자의 현재 뱃지 목록을 미리 저장해 둡니다.
    profile, created = Profile.objects.get_or_create(user=request.user)
    badges_before = set(profile.badges.values_list('id', flat=True))

    questions = Question.objects.filter(pk__in=question_ids)
    correct_answers = 0
    results_data = []

    # 채점 로직
    for question in questions:
        q_id_str = str(question.id)
        user_answer = user_answers.get(q_id_str)
        is_correct = False
        selected_choice = None
        short_answer_text = None

        try:
            if question.question_type == '객관식':
                selected_choice = Choice.objects.get(pk=user_answer) if user_answer else None
                correct_choice = question.choice_set.get(is_correct=True)
                if selected_choice == correct_choice:
                    is_correct = True
            
            elif question.question_type == '다중선택':
                correct_choice_ids = set(question.choice_set.filter(is_correct=True).values_list('id', flat=True))
                user_choice_ids = set(user_answer if isinstance(user_answer, list) else [])
                if correct_choice_ids and correct_choice_ids == user_choice_ids:
                    is_correct = True
                short_answer_text = ", ".join(map(str, user_choice_ids))

            elif question.question_type == '주관식':
                correct_answer_text = question.choice_set.get(is_correct=True).choice_text
                short_answer_text = user_answer if user_answer else ""
                if short_answer_text.strip().lower() == correct_answer_text.strip().lower():
                    is_correct = True
        except Choice.DoesNotExist:
            pass

        if is_correct:
            correct_answers += 1
        
        results_data.append({
            'question': question,
            'selected_choice': selected_choice,
            'short_answer_text': short_answer_text,
            'is_correct': is_correct
        })
    
    # --- [핵심 수정 1] 점수 계산 ---
    total_questions = len(question_ids)
    score = int((correct_answers / total_questions) * 100) if total_questions > 0 else 0
    
    # --- [핵심 수정 2] 80점 이상일 경우 '합격'으로 처리 ---
    is_pass = (score >= 80)
    
    # --- [핵심 수정 3] TestResult 생성 시 is_pass 필드 추가 ---
    test_result = TestResult.objects.create(
        user=request.user,
        quiz=attempt.quiz,
        score=score,
        attempt=attempt,
        is_pass=is_pass # <-- 합격 여부 저장
    )

    award_badges(request.user, test_result)

    # UserAnswer(개별 답안) 객체들을 저장합니다.
    for result in results_data:
        if result['selected_choice'] or (result['short_answer_text'] is not None):
            UserAnswer.objects.create(
                test_result=test_result,
                question=result['question'],
                selected_choice=result['selected_choice'],
                short_answer_text=result['short_answer_text'],
                is_correct=result['is_correct']
            )

    # 응시 요청 상태를 '완료됨'으로 변경합니다.
    if attempt:
        attempt.status = '완료됨'
        attempt.save()

    # 뱃지 획득 후, 프로필 정보를 DB에서 새로고침하여 최신 뱃지 목록을 가져옵니다.
    profile.refresh_from_db()
    badges_after = set(profile.badges.values_list('id', flat=True))
    
    # 이전 뱃지 목록과 비교하여, 새로 추가된 뱃지만 찾아냅니다.
    new_badge_ids = badges_after - badges_before
    newly_awarded_badges = Badge.objects.filter(id__in=new_badge_ids)

    # --- [핵심 추가] 2회 불합격 시 PL에게 이메일 발송 ---
    if not test_result.is_pass:
        # 이 시험에서 '불합격'한 횟수를 셉니다.
        failure_count = TestResult.objects.filter(
            user=request.user, 
            quiz=attempt.quiz, 
            is_pass=False
        ).count()
        
        # [수정] 정확히 2회가 되었을 때만 메일을 발송합니다.
        if failure_count == 2:
            if hasattr(request.user, 'profile') and request.user.profile.pl and request.user.profile.pl.email:
                pl = request.user.profile.pl
                subject = f"[CBT 경고] 교육생 면담 요청: {profile.name}"
                message = (
                    f"{pl.name}님,\n\n"
                    f"귀하의 담당 교육생인 {profile.name} (사번: {profile.employee_id}, 기수: {profile.class_number}기)이\n"
                    f"'{attempt.quiz.title}' 시험에서 누적 2회 불합격하였습니다.\n\n"
                    "바쁘시겠지만 PMTC로 직접 오셔서 교육생 면담 및 지도가 필요합니다.\n\n"
                    "- CBT 관리 시스템"
                )
                
                try:
                    send_mail(
                        subject,
                        message,
                        os.environ.get('EMAIL_HOST_USER'), # 발신자 (settings.py)
                        [pl.email], # 수신자 (PL 이메일)
                        fail_silently=False,
                    )
                except Exception as e:
                    # (선택사항) 이메일 발송 실패 시, 관리자에게 로그를 남깁니다.
                    print(f"PL 경고 메일 발송 실패: {e}")

    # --- [누락되었던 부분 수정] ---
    # context에 newly_awarded_badges와 test_result를 추가하여 템플릿으로 전달합니다.
    context = {
        'results_data': results_data,
        'score': score,
        'total_questions': total_questions,
        'correct_answers': correct_answers,
        'newly_awarded_badges': newly_awarded_badges,
        'test_result': test_result,
        'is_pass': is_pass,
    }

    # 사용이 끝난 세션 데이터를 정리합니다.
    request.session.pop('quiz_questions', None)
    request.session.pop('user_answers', None)
    request.session.pop('attempt_id', None)

    return render(request, 'quiz/quiz_results.html', context)
    
@login_required
def upload_quiz(request):
    if not request.user.is_staff:
        return redirect('quiz:index')

    if request.method == 'POST':
        try:
            excel_file = request.FILES['excel_file']
            # 빈 칸(NaN)을 빈 문자열('')로 안전하게 처리합니다.
            df = pd.read_excel(excel_file).fillna('')
            
            error_count = 0
            success_count = 0

            for index, row in df.iterrows():
                
                # --- [핵심 수정 1] Question Type 처리 ---
                q_type_excel = row['question_type'] # 엑셀에서 읽은 값
                q_type_db = q_type_excel           # DB에 저장할 값

                # 1-1. 하위 호환성: "주관식"이라고 쓰면 -> "주관식 (단일정답)"으로 자동 변환
                if q_type_excel == '주관식':
                    q_type_db = '주관식 (단일정답)'
                
                # 1-2. DB에 허용된 타입인지 검사 (models.py와 일치해야 함)
                allowed_types = ['객관식', '다중선택', '주관식 (단일정답)', '주관식 (복수정답)']
                if q_type_db not in allowed_types:
                    messages.error(request, f"업로드 실패 (행 {index + 2}): 'question_type'('{q_type_excel}')이 잘못되었습니다. [객관식, 다중선택, 주관식 (단일정답), 주관식 (복수정답)] 중 하나여야 합니다.")
                    error_count += 1
                    continue # 이 행은 건너뛰고 다음 행으로
                # ----------------------------------------
                
                quiz, created = Quiz.objects.get_or_create(title=row['quiz_title'])
                
                question = Question.objects.create(
                    quiz=quiz,
                    question_text=row['question_text'],
                    question_type=q_type_db, # <--- 수정된 DB용 타입으로 저장
                    difficulty=row['difficulty']
                )

                # --- 태그 처리 로직 (기존과 동일) ---
                if row['tags']:
                    tag_names = [tag.strip() for tag in str(row['tags']).split(',') if tag.strip()]
                    for tag_name in tag_names:
                        tag, created = Tag.objects.get_or_create(name=tag_name)
                        question.tags.add(tag)
                # --------------------------------

                # --- [핵심 수정 2] Choice(정답/보기) 저장 로직 ---
                
                # 2-1. 복수 정답/보기를 허용하는 타입들
                # [수정] '주관식 (복수정답)'을 '다중선택'과 동일한 로직으로 처리
                if q_type_db in ['객관식', '다중선택', '주관식 (복수정답)']:
                    
                    # correct_choice로 시작하는 모든 열을 정답으로 처리
                    for col in df.columns:
                        if str(col).startswith('correct_choice') and row[col]:
                            Choice.objects.create(question=question, choice_text=row[col], is_correct=True)
                    
                    # 오답 보기는 '객관식', '다중선택'일 때만 추가
                    if q_type_db in ['객관식', '다중선택']:
                        for col in df.columns:
                            if str(col).startswith('other_choice') and row[col]:
                                Choice.objects.create(question=question, choice_text=row[col], is_correct=False)
                
                # 2-2. 단일 정답만 허용하는 타입
                elif q_type_db == '주관식 (단일정답)':
                    if row['correct_choice']:
                        Choice.objects.create(question=question, choice_text=row['correct_choice'], is_correct=True)
                # ------------------------------------------

                success_count += 1
            
            if success_count > 0:
                messages.success(request, f"{success_count}개의 문제가 성공적으로 업로드되었습니다.")
            if error_count > 0:
                messages.warning(request, f"{error_count}개의 문제는 오류로 인해 건너뛰었습니다. (상세 내용 확인)")

        except Exception as e:
            messages.error(request, f"업로드 중 오류가 발생했습니다: {e}")

        return redirect('quiz:upload_quiz')

    return render(request, 'quiz/upload_quiz.html')

@login_required
def my_results_index(request):
    # 1. 사용자가 응시한 시험 '종류'를 중복 없이 가져옵니다.
    quizzes_taken = Quiz.objects.filter(testresult__user=request.user).distinct()
    context = {'quizzes_taken': quizzes_taken}
    return render(request, 'quiz/my_results_index.html', context)

@login_required
def my_results_by_quiz(request, quiz_id):
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    all_results = TestResult.objects.filter(user=request.user, quiz=quiz).order_by('-completed_at')
    
    for result in all_results:
        newer_attempts_count = TestResult.objects.filter(
            user=request.user, quiz=result.quiz, completed_at__gt=result.completed_at
        ).count()
        total_attempts_for_quiz = TestResult.objects.filter(user=request.user, quiz=result.quiz).count()
        result.attempt_number = total_attempts_for_quiz - newer_attempts_count
        
    sorted_results = sorted(list(all_results), key=lambda r: r.completed_at, reverse=True)
    
    # --- [누락되었던 부분] 페이지네이션 로직 ---
    paginator = Paginator(sorted_results, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'quiz': quiz,
        'page_obj': page_obj # test_results -> page_obj
    }
    return render(request, 'quiz/my_results_list.html', context)

@login_required
def result_detail(request, result_id):
    # 현재 사용자의 특정 시험 결과를 가져옵니다.
    result = get_object_or_404(TestResult, pk=result_id, user=request.user)
    
    # 위 시험 결과에 연결된 답변들 중, '틀린' 것만 가져옵니다.
    incorrect_answers = result.useranswer_set.filter(is_correct=False)
    
    context = {
        'result': result,
        'incorrect_answers': incorrect_answers
    }
    return render(request, 'quiz/result_detail.html', context)

@login_required
def start_quiz(request, attempt_id):
    # 현재 사용자의 응시 요청을 가져옵니다. (기존과 동일)
    attempt = get_object_or_404(QuizAttempt, pk=attempt_id, user=request.user)

    # 이미 완료된 시험인지 확인합니다. (기존과 동일)
    existing_result = TestResult.objects.filter(attempt=attempt).first()
    if existing_result:
        if attempt.status != '완료됨':
            attempt.status = '완료됨'; attempt.save()
        messages.error(request, "이미 완료된 시험입니다. 결과 페이지에서 다시 확인해주세요.")
        return redirect('quiz:result_detail', result_id=existing_result.id)
        
    # '승인됨' 상태가 아니면 시작할 수 없습니다. (기존과 동일)
    if attempt.status != '승인됨':
        messages.error(request, "아직 승인되지 않았거나 유효하지 않은 시험입니다.")
        return redirect('quiz:index')

    quiz = attempt.quiz
    final_questions = []

    # --- [최종 수정] 문제 출제 방식에 따라 다른 로직을 실행합니다 ---
    if quiz.generation_method == Quiz.GenerationMethod.FIXED and quiz.exam_sheet:
        # '지정' 방식일 경우, 오직 문제 세트의 문제들만 가져옵니다.
        final_questions = list(quiz.exam_sheet.questions.all())
    
    else: # '랜덤' 방식일 경우 (사용자님께서 보내주신 기존 로직)
        questions_hard = list(quiz.question_set.filter(difficulty='상'))
        questions_medium = list(quiz.question_set.filter(difficulty='중'))
        questions_easy = list(quiz.question_set.filter(difficulty='하'))
        
        selected_hard = random.sample(questions_hard, min(len(questions_hard), 8))
        selected_medium = random.sample(questions_medium, min(len(questions_medium), 9))
        selected_easy = random.sample(questions_easy, min(len(questions_easy), 8))

        initial_selection = selected_hard + selected_medium + selected_easy
        shortfall = 25 - len(initial_selection)

        if shortfall > 0:
            all_questions = questions_hard + questions_medium + questions_easy
            remaining_pool = [q for q in all_questions if q not in initial_selection]
            fill_in_questions = random.sample(remaining_pool, min(len(remaining_pool), shortfall))
            final_questions = initial_selection + fill_in_questions
        else:
            final_questions = initial_selection
    
    random.shuffle(final_questions)
    # ---------------------------------------------

    # 출제할 문제가 없는 경우를 대비한 안전장치
    if not final_questions:
        messages.error(request, "출제할 문제가 없습니다. '퀴즈' 설정에서 '문제 세트'가 올바르게 선택되었는지 확인하세요.")
        return redirect('quiz:index')

    # 세션에 최종 문제 목록 저장 (기존과 동일)
    request.session['quiz_questions'] = [q.id for q in final_questions]
    request.session['user_answers'] = {}
    request.session['attempt_id'] = attempt.id

    return HttpResponseRedirect(reverse('quiz:take_quiz', args=(1,)))

@login_required
def submit_quiz(request):
    # 최종 제출 시, 응시 요청 상태를 '완료됨'으로 변경
    attempt_id = request.session.get('attempt_id')
    if attempt_id:
        attempt = QuizAttempt.objects.get(pk=attempt_id)
        if attempt.status != '완료됨':
            attempt.status = '완료됨'
            attempt.save()

    # 결과 페이지로 이동
    return redirect('quiz:quiz_results')

@login_required
def my_incorrect_answers_index(request):
    # 1. 사용자가 틀린 적이 있는 시험 '종류'를 중복 없이 가져옵니다.
    incorrect_answers = UserAnswer.objects.filter(test_result__user=request.user, is_correct=False)
    quizzes_with_incorrects = Quiz.objects.filter(question__useranswer__in=incorrect_answers).distinct()

    context = {'quizzes_with_incorrects': quizzes_with_incorrects}
    return render(request, 'quiz/my_incorrect_answers_index.html', context)

@login_required
def my_incorrect_answers_by_quiz(request, quiz_id):
    # 2. 특정 시험에서 틀린 문제만 가져옵니다.
    quiz = get_object_or_404(Quiz, pk=quiz_id)

    incorrect_answers = UserAnswer.objects.filter(
        test_result__user=request.user, 
        question__quiz=quiz,
        is_correct=False
    )
    incorrect_question_ids = incorrect_answers.values_list('question', flat=True).distinct()
    incorrect_questions = Question.objects.filter(pk__in=incorrect_question_ids)

    context = {
        'quiz': quiz,
        'incorrect_questions': incorrect_questions
    }
    return render(request, 'quiz/incorrect_answers_list.html', context)

# quiz/views.py

@login_required
def dashboard(request):
    if not request.user.is_staff:
        return redirect('quiz:index')

    # --- 기본 통계 (이전과 동일) ---
    total_users = User.objects.count()
    total_quizzes = Quiz.objects.count()
    average_score = TestResult.objects.aggregate(avg_score=Avg('score'))['avg_score']

    # --- 수정된 부분: 퀴즈별로 가장 많이 틀린 문제 계산 ---
    stats_by_quiz = {}
    quizzes = Quiz.objects.all()
    for quiz in quizzes:
        most_incorrect = UserAnswer.objects.filter(
            is_correct=False, 
            question__quiz=quiz
        ).values(
            'question__question_text', 
            'question__difficulty'
        ).annotate(
            incorrect_count=Count('id')
        ).order_by('-incorrect_count')[:5]

        stats_by_quiz[quiz.title] = most_incorrect
    # ---------------------------------------------------

    context = {
        'total_users': total_users,
        'total_quizzes': total_quizzes,
        'average_score': average_score,
        'stats_by_quiz': stats_by_quiz, # <-- 전달하는 데이터 변경
    }
    return render(request, 'quiz/dashboard.html', context)

@login_required
def personal_dashboard(request):
    profile, created = Profile.objects.get_or_create(user=request.user)
    summary_data = []
    quizzes_taken = Quiz.objects.filter(testresult__user=request.user).distinct()

    for quiz in quizzes_taken:
        results_for_quiz = TestResult.objects.filter(user=request.user, quiz=quiz)

        # --- [핵심 수정] 1차 점수를 찾습니다 ---
        # 가장 먼저 본 시험(completed_at이 가장 작은)을 찾습니다.
        first_attempt = results_for_quiz.order_by('completed_at').first()
        first_score = first_attempt.score if first_attempt else None
        # ------------------------------------

        avg_score = results_for_quiz.aggregate(Avg('score'))['score__avg']
        max_score = results_for_quiz.aggregate(Max('score'))['score__max']
        attempts = results_for_quiz.count()

        summary_data.append({
            'title': quiz.title,
            'first_score': first_score, # 1차 점수 추가
            'avg_score': avg_score,
            'max_score': max_score,
            'attempts': attempts,
        })

    total_attempts = TestResult.objects.filter(user=request.user).count()
    overall_average_score = TestResult.objects.filter(user=request.user).aggregate(Avg('score'))['score__avg']

    context = {
        'total_attempts': total_attempts,
        'overall_average_score': overall_average_score,
        'summary_data': summary_data,
        'user_badges': profile.badges.all(), #
    }
    return render(request, 'quiz/personal_dashboard.html', context)

@login_required
def start_group_quiz(request, quiz_id):
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    # 그룹 배정을 통해 시험을 시작하므로, '그룹 배정' 타입의 응시 요청을 자동으로 생성하고 즉시 '승인됨' 상태로 만듭니다.
    attempt = QuizAttempt.objects.create(
        user=request.user,
        quiz=quiz,
        status=QuizAttempt.Status.APPROVED,
        assignment_type=QuizAttempt.AssignmentType.GROUP
    )
    # 생성된 응시 요청 ID를 가지고 실제 시험 시작 함수로 보냅니다.
    return redirect('quiz:start_quiz', attempt_id=attempt.id)

@login_required
def export_student_data(request):
    if not request.user.is_staff:
        return redirect('quiz:index')

    # 모든 시험 결과를 관련 사용자 및 프로필 정보와 함께 가져옵니다.
    results = TestResult.objects.select_related('user', 'user__profile', 'quiz').order_by('user__username', 'completed_at')

    data_list = []
    for result in results:
        profile = result.user.profile if hasattr(result.user, 'profile') else None
        data_list.append({
            '사용자 ID': result.user.username,
            '이름': profile.name if profile else '',
            '사번': profile.employee_id if profile else '',
            '기수': f"{profile.class_number}기" if profile and profile.class_number else '',
            '공정': profile.process if profile else '',
            'PL님 성함': profile.pl_name if profile else '',
            '시험 종류': result.quiz.title,
            '회차': result.attempt_number,
            '점수': result.score,
            '응시 완료 시간': result.completed_at.strftime('%Y-%m-%d %H:%M:%S'),
        })

    # Pandas DataFrame으로 변환
    df = pd.DataFrame(data_list)

    # 엑셀 파일로 변환하여 HttpResponse로 반환
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = 'attachment; filename="student_data_export.xlsx"'
    df.to_excel(response, index=False)

    return response


def award_badges(user, test_result):
    
    # 1. 사용자의 프로필과 뱃지 목록을 가져옵니다.
    try:
        user_profile = user.profile
        user_badges = user_profile.badges.all()
        user_badge_names = set(user_badges.values_list('name', flat=True))
    except Profile.DoesNotExist:
        # 프로필이 없는 비상 상황 (예: 슈퍼유저)
        return
    except Exception as e:
        print(f"뱃지 로직 오류 (프로필 로드 실패): {e}")
        return

    # 2. 앞으로 추가할 뱃지를 담을 리스트
    badges_to_add = []
    
    # 3. DB에 있는 모든 뱃지 객체를 가져옵니다. (효율성을 위해 dict로)
    all_badges = {badge.name: badge for badge in Badge.objects.all()}

    # --- 4. 뱃지 조건 검사 ---
    
   # [1] 첫걸음: 첫 번째 시험을 완료
    badge_name = '첫걸음'
    if badge_name not in user_badge_names:
        if TestResult.objects.filter(user=user).count() == 1: # 이번이 첫 시험임
            if all_badges.get(badge_name):
                badges_to_add.append(all_badges[badge_name])
                user_badge_names.add(badge_name)

    # [2] 퍼펙트: 100점으로 시험을 통과했습니다. (횟수 무관, '완벽한 시작'과 다름)
    badge_name = '퍼펙트'
    if test_result.score == 100 and badge_name not in user_badge_names:
        if all_badges.get(badge_name):
            badges_to_add.append(all_badges[badge_name])
            user_badge_names.add(badge_name)

    # [3] 완벽한 시작: '처음으로' 100점을 달성했습니다.
    badge_name = '완벽한 시작'
    if test_result.score == 100 and badge_name not in user_badge_names:
        previous_100s = TestResult.objects.filter(
            user=user, score=100
        ).exclude(pk=test_result.pk).exists() # 이번 점수 제외
        if not previous_100s:
            if all_badges.get(badge_name):
                badges_to_add.append(all_badges[badge_name])
                user_badge_names.add(badge_name)

    # [4] 지니어스: '상' 난이도 시험에서 90점 이상
    # (주의: '상' 난이도 질문이 1개라도 포함된 퀴즈로 가정)
    badge_name = '지니어스'
    if test_result.score >= 90 and badge_name not in user_badge_names:
        quiz_has_hard_questions = test_result.quiz.question_set.filter(difficulty='상').exists()
        if quiz_has_hard_questions:
            if all_badges.get(badge_name):
                badges_to_add.append(all_badges[badge_name])
                user_badge_names.add(badge_name)

    # [5] 아차상: 98점 또는 99점
    badge_name = '아차상'
    if (test_result.score == 98 or test_result.score == 99) and badge_name not in user_badge_names:
        if all_badges.get(badge_name):
            badges_to_add.append(all_badges[badge_name])
            user_badge_names.add(badge_name)

    # [6] 아슬아슬: 60~65점 사이
    badge_name = '아슬아슬'
    if 60 <= test_result.score <= 65 and badge_name not in user_badge_names:
        if all_badges.get(badge_name):
            badges_to_add.append(all_badges[badge_name])
            user_badge_names.add(badge_name)

    # [7] 절반의 성공: 정확히 50점
    badge_name = '절반의 성공'
    if test_result.score == 50 and badge_name not in user_badge_names:
        if all_badges.get(badge_name):
            badges_to_add.append(all_badges[badge_name])
            user_badge_names.add(badge_name)

    # [8] 괜찮아, 다시 하면 돼: 30점 이하
    badge_name = '괜찮아, 다시 하면 돼'
    if test_result.score <= 30 and badge_name not in user_badge_names:
        if all_badges.get(badge_name):
            badges_to_add.append(all_badges[badge_name])
            user_badge_names.add(badge_name)

    # [9] 빵점...?!: 0점
    badge_name = '빵점...?!'
    if test_result.score == 0 and badge_name not in user_badge_names:
        if all_badges.get(badge_name):
            badges_to_add.append(all_badges[badge_name])
            user_badge_names.add(badge_name)

    # [10] 재도전자: 같은 종류의 시험 3회 이상 응시
    badge_name = '재도전자'
    if badge_name not in user_badge_names:
        attempts_count = TestResult.objects.filter(
            user=user, quiz=test_result.quiz
        ).count()
        if attempts_count >= 3:
            if all_badges.get(badge_name):
                badges_to_add.append(all_badges[badge_name])
                user_badge_names.add(badge_name)

    # [11] 성실한 응시자: 총 시험 횟수 10회 돌파
    badge_name = '성실한 응시자'
    if badge_name not in user_badge_names:
        total_attempts = TestResult.objects.filter(user=user).count()
        if total_attempts >= 10:
            if all_badges.get(badge_name):
                badges_to_add.append(all_badges[badge_name])
                user_badge_names.add(badge_name)

    # [12] 연승가도: 3개 시험 연속 합격
    badge_name = '연승가도'
    if test_result.is_pass and badge_name not in user_badge_names:
        last_three_results = TestResult.objects.filter(user=user).order_by('-completed_at')[:3]
        if len(last_three_results) == 3 and all(r.is_pass for r in last_three_results):
            if all_badges.get(badge_name):
                badges_to_add.append(all_badges[badge_name])
                user_badge_names.add(badge_name)

    # [13] 불사조: 불합격했던 시험을 재응시하여 합격
    badge_name = '불사조'
    if test_result.is_pass and badge_name not in user_badge_names:
        had_failed_before = TestResult.objects.filter(
            user=user, quiz=test_result.quiz, is_pass=False
        ).exists()
        if had_failed_before:
             if all_badges.get(badge_name):
                badges_to_add.append(all_badges[badge_name])
                user_badge_names.add(badge_name)

    # [14] 노력의 결실: 같은 시험 1차 점수보다 30점 이상 향상
    badge_name = '노력의 결실'
    if badge_name not in user_badge_names:
        first_attempt = TestResult.objects.filter(
            user=user, quiz=test_result.quiz
        ).order_by('completed_at').first()
        if first_attempt and first_attempt.pk != test_result.pk:
            if test_result.score >= first_attempt.score + 30:
                if all_badges.get(badge_name):
                    badges_to_add.append(all_badges[badge_name])
                    user_badge_names.add(badge_name)

    # [15] 정복자: 사이트의 모든 종류의 시험에 '응시'
    badge_name = '정복자'
    if badge_name not in user_badge_names:
        all_quiz_ids = set(Quiz.objects.values_list('id', flat=True))
        attempted_quiz_ids = set(TestResult.objects.filter(user=user).values_list('quiz_id', flat=True).distinct())
        
        if all_quiz_ids and all_quiz_ids.issubset(attempted_quiz_ids):
            if all_badges.get(badge_name):
                badges_to_add.append(all_badges[badge_name])
                user_badge_names.add(badge_name)

    # [16] all 100: 사이트의 모든 종류의 시험에서 100점
    badge_name = 'all 100'
    if test_result.score == 100 and badge_name not in user_badge_names:
        all_quiz_ids = set(Quiz.objects.values_list('id', flat=True))
        passed_100_quiz_ids = set(TestResult.objects.filter(user=user, score=100).values_list('quiz_id', flat=True).distinct())

        if all_quiz_ids and all_quiz_ids.issubset(passed_100_quiz_ids):
            if all_badges.get(badge_name):
                badges_to_add.append(all_badges[badge_name])
                user_badge_names.add(badge_name)

    # [17] 공정 마스터: '공정' 카테고리 시험 3개 이상 '합격'
    badge_name = '공정 마스터'
    if test_result.is_pass and test_result.quiz.category == Quiz.Category.PROCESS and badge_name not in user_badge_names:
        passed_process_quizzes_count = TestResult.objects.filter(
            user=user, 
            quiz__category=Quiz.Category.PROCESS, 
            is_pass=True
        ).values('quiz_id').distinct().count()
        
        if passed_process_quizzes_count >= 3:
            if all_badges.get(badge_name):
                badges_to_add.append(all_badges[badge_name])
                user_badge_names.add(badge_name)

    # [18] 꾸준함: 3일 연속 시험 응시
    badge_name = '꾸준함'
    if badge_name not in user_badge_names:
        # 사용자가 시험을 본 '날짜' 목록을 중복 없이, 최신순으로 3개 가져옴
        recent_test_dates = list(TestResult.objects.filter(user=user).dates('completed_at', 'day', order='DESC')[:3])
        if len(recent_test_dates) == 3:
            # 날짜 3개가 연속되는지 확인 (예: 15일, 14일, 13일)
            is_consecutive = (
                recent_test_dates[0] - timedelta(days=1) == recent_test_dates[1] and
                recent_test_dates[1] - timedelta(days=1) == recent_test_dates[2]
            )
            if is_consecutive:
                if all_badges.get(badge_name):
                    badges_to_add.append(all_badges[badge_name])
                    user_badge_names.add(badge_name)

    # --- 5. 뱃지 일괄 추가 ---
    if badges_to_add:
        user_profile.badges.add(*badges_to_add)

    # --- 6. 뱃지를 획득한 후, '개수' 뱃지 체크 ('수집가', '뱃지 콜렉터') ---
    
    # (user_badge_names set은 이번에 새로 딴 뱃지 이름도 포함하고 있음)
    final_badge_count = len(user_badge_names) 
    
    # [19] 수집가 (5개)
    badge_name = '수집가'
    if final_badge_count >= 5 and badge_name not in user_badge_names:
        if all_badges.get(badge_name):
            user_profile.badges.add(all_badges[badge_name])
            user_badge_names.add(badge_name) # (다음 티어 체크를 위해 set에 수동 추가)

    # [20] (보너스) 뱃지 콜렉터 (10개)
    badge_name = '뱃지 콜렉터' # (Admin에 이 이름으로 뱃지 추가 필요)
    if final_badge_count >= 10 and badge_name not in user_badge_names:
         if all_badges.get(badge_name):
            user_profile.badges.add(all_badges[badge_name])
            user_badge_names.add(badge_name)