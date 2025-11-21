import json
import random
import pandas as pd
import os
from datetime import timedelta

from django.utils import timezone
from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.views.decorators.cache import cache_control
from django.core.mail import send_mail
from django.contrib.admin.views.decorators import staff_member_required
from django.views.decorators.http import require_POST

# [핵심] 데이터 분석 및 집계를 위한 필수 모듈 (누락된 부분 추가됨)
from django.db.models import Avg, Count, Q, Max, F, Case, When, Value, CharField

# accounts 앱의 모델들
from accounts.models import (
    Profile, Badge, EvaluationRecord, EvaluationCategory, 
    ManagerEvaluation, Cohort, Company, Process
)

# quiz 앱의 모델들
from .models import (
    Quiz, Question, Choice, TestResult, UserAnswer, 
    QuizAttempt, ExamSheet, Tag
)

# 폼
from .forms import EvaluationForm


# 1. '마이 페이지'
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
    if hasattr(user, 'profile') and user.profile.process:
        user_process = user.profile.process

    # -------------------------------------------------------
    # [1] 공통 과목 (Common) - 누구나 무조건 보임
    # -------------------------------------------------------
    all_common_quizzes = Quiz.objects.filter(
        category=Quiz.Category.COMMON
    ).distinct()

    # -------------------------------------------------------
    # [2] 권한 필터 설정 (관리자 프리패스 추가)
    # -------------------------------------------------------
    if user.is_staff:
        # 관리자는 조건 없이 모든 권한을 가짐
        permission_query = Q()
    else:
        # 일반 유저는 내 그룹이나 아이디가 포함된 것만 조회
        permission_query = Q(allowed_groups__in=user_groups) | Q(allowed_users=user)

    # -------------------------------------------------------
    # [3] '나의 공정' 퀴즈 목록 (My Process & Assigned)
    # -------------------------------------------------------
    # 조건: (1.시험 공정이 내 공정임) OR (2.내 아이디가 직접 할당됨) OR (3.내 그룹이 할당됨)
    # 이렇게 해야 타 공정 시험이라도 나에게 할당되면 '나의 공정'으로 넘어옵니다.
    
    my_process_condition = Q(associated_process=user_process) | Q(allowed_users=user) | Q(allowed_groups__in=user_groups)
    
    # 관리자라면 모든 공정 시험을 '나의 공정'처럼 볼 수 있게 하거나, 
    # 원한다면 관리자도 자신의 Profile 공정에 따라 나누어 볼 수 있습니다.
    # 여기서는 관리자는 '모든 공정 시험'을 '나의 공정' 탭에서 보도록 설정했습니다.
    if user.is_staff:
        my_process_quizzes_list = Quiz.objects.filter(
            category=Quiz.Category.PROCESS
        ).distinct()
    else:
        my_process_quizzes_list = Quiz.objects.filter(
            permission_query,             # 볼 수 있는 권한이 있어야 하고
            Q(category=Quiz.Category.PROCESS), # 공정 시험이어야 하고
            my_process_condition          # 내 공정이거나 나한테 할당된 것
        ).distinct()

    # -------------------------------------------------------
    # [4] '기타 공정' 퀴즈 목록 (Other Process)
    # -------------------------------------------------------
    # 조건: 공정 시험이면서, 위 [3]번 리스트('나의 공정')에 포함되지 않은 나머지
    
    if user.is_staff:
        # 관리자는 위에서 다 보여줬으므로 기타는 비워둡니다 (중복 방지)
        other_process_quizzes_list = Quiz.objects.none()
    else:
        other_process_quizzes_list = Quiz.objects.filter(
            permission_query,             # 볼 수 있는 권한이 있고
            category=Quiz.Category.PROCESS # 공정 시험인데
        ).exclude(
            id__in=my_process_quizzes_list.values('id') # 이미 '나의 공정'에 있는건 제외
        ).distinct()


    # -------------------------------------------------------
    # [5] 합격 여부 카운팅 (로직 유지)
    # -------------------------------------------------------
    all_common_passed = False
    passed_common_count = TestResult.objects.filter(
        user=user, quiz__in=all_common_quizzes, is_pass=True
    ).values('quiz').distinct().count()
    
    if all_common_quizzes.count() > 0 and passed_common_count >= all_common_quizzes.count():
        all_common_passed = True
    elif all_common_quizzes.count() == 0:
        all_common_passed = True

    all_my_process_passed = False
    passed_my_process_count = TestResult.objects.filter(
        user=user, quiz__in=my_process_quizzes_list, is_pass=True
    ).values('quiz').distinct().count()
    
    if my_process_quizzes_list.count() > 0 and passed_my_process_count >= my_process_quizzes_list.count():
        all_my_process_passed = True
    elif my_process_quizzes_list.count() == 0:
        all_my_process_passed = True

    # -------------------------------------------------------
    # [6] 헬퍼 함수 (상태 결정)
    # -------------------------------------------------------
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

            # (개인 지정 시험인 경우 바로 그룹 로직 건너뜀)
            is_individually_assigned = quiz.allowed_users.filter(id=user.id).exists()
            is_group_assigned = quiz.allowed_groups.filter(id__in=user_groups).exists()
            
            if is_group_assigned and not is_individually_assigned:
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

    my_process_has_override = any(quiz.user_status in ['승인됨', '대기중'] for quiz in my_process_quizzes)
    other_process_has_override = any(quiz.user_status in ['승인됨', '대기중'] for quiz in other_process_quizzes)

    context = {
        'common_quizzes': common_quizzes,
        'my_process_quizzes': my_process_quizzes,
        'other_process_quizzes': other_process_quizzes,
        'all_common_passed': all_common_passed,
        'all_my_process_passed': all_my_process_passed,
        'my_process_has_override': my_process_has_override,
        'other_process_has_override': other_process_has_override,
    }
    return render(request, 'quiz/index.html', context)

@login_required
def request_quiz(request, quiz_id):
    quiz = get_object_or_404(Quiz, pk=quiz_id)

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

@login_required
@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def take_quiz(request, page_number):
    question_ids = request.session.get('quiz_questions')
    attempt_id = request.session.get('attempt_id')

    if not attempt_id:
        messages.error(request, "잘못된 접근입니다. 시험을 다시 시작해주세요.")
        return redirect('quiz:index')

    attempt = get_object_or_404(QuizAttempt, pk=attempt_id)

    if attempt.status == '완료됨':
        messages.info(request, "이미 완료된 시험입니다. 결과 페이지로 이동합니다.")
        result = attempt.testresult_set.first() 
        if result:
            return redirect('quiz:result_detail', result_id=result.id)
        else:
            return redirect('quiz:my_results_index')

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
        'is_in_test_mode': True,
    }
    return render(request, 'quiz/take_quiz.html', context)

@login_required
def submit_page(request, page_number):
    attempt_id = request.session.get('attempt_id')
    if not attempt_id:
        messages.error(request, "유효하지 않은 시험 접근입니다.")
        return redirect('quiz:index')

    attempt = get_object_or_404(QuizAttempt, pk=attempt_id)
    if attempt.status == '완료됨':
        messages.info(request, "이미 완료된 시험입니다.")
        result = attempt.testresult_set.first()
        return redirect('quiz:result_detail', result_id=result.id) if result else redirect('quiz:my_results_index')

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
        elif question.question_type == '주관식 (단일정답)' or question.question_type == '주관식 (복수정답)':
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

@staff_member_required
def bulk_add_sheet_view(request):
    # [수정됨] created_at 대신 id 역순(-id) 사용
    quizzes = Quiz.objects.all().order_by('-id') 
    return render(request, 'quiz/bulk_add_sheet.html', {'quizzes': quizzes})

@staff_member_required
@require_POST
def bulk_add_sheet_save(request):
    try:
        body = json.loads(request.body)
        quiz_id = body.get('quiz_id')
        raw_data = body.get('data', [])
        
        if not quiz_id:
            return JsonResponse({'status': 'error', 'message': '시험(Quiz)이 선택되지 않았습니다.'})

        target_quiz = Quiz.objects.get(id=quiz_id)
        success_count = 0

        for row in raw_data:
            # [0:문제, 1:유형, 2:난이도, 3:태그, 4:보기1, 5:보기2, 6:보기3, 7:보기4, 8:정답]
            question_text = str(row[0] or '').strip()
            if not question_text: continue

            q_type = str(row[1] or '객관식').strip()
            difficulty = str(row[2] or '하').strip()
            
            # 태그 처리
            new_question = Question.objects.create(
                quiz=target_quiz,
                question_text=question_text,
                question_type=q_type,
                difficulty=difficulty
            )
            
            tags_str = str(row[3] or '').strip()
            if tags_str:
                for tag_name in tags_str.split(','):
                    if tag_name.strip():
                        tag, _ = Tag.objects.get_or_create(name=tag_name.strip())
                        new_question.tags.add(tag)

            answer_val = str(row[8] or '').strip() # 사용자가 입력한 정답 값

            # (A) 주관식
            if '주관식' in q_type:
                if answer_val:
                    Choice.objects.create(
                        question=new_question,
                        choice_text=answer_val,
                        is_correct=True
                    )
            
            # (B) 객관식/다중선택 [수정된 부분]
            else:
                choices = [row[4], row[5], row[6], row[7]]
                for i, choice_text in enumerate(choices):
                    choice_text = str(choice_text or '').strip()
                    if choice_text:
                        is_correct = False
                        
                        # 1. 숫자로 비교 (예: '4' == index+1)
                        if answer_val == str(i + 1):
                            is_correct = True
                            
                        # 2. [핵심 추가] 글자로 비교 (예: '에칭기' == '에칭기')
                        elif answer_val == choice_text:
                            is_correct = True
                        
                        Choice.objects.create(
                            question=new_question,
                            choice_text=choice_text,
                            is_correct=is_correct
                        )
            
            success_count += 1

        return JsonResponse({'status': 'success', 'count': success_count})

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})

@login_required
def quiz_results(request):
    question_ids = request.session.get('quiz_questions', [])
    user_answers = request.session.get('user_answers', {})
    attempt_id = request.session.get('attempt_id')
    attempt = QuizAttempt.objects.get(pk=attempt_id) if attempt_id else None

    if not question_ids:
        messages.error(request, "채점할 시험 정보가 없습니다.")
        return redirect('quiz:index')

    profile, created = Profile.objects.get_or_create(user=request.user)
    badges_before = set(profile.badges.values_list('id', flat=True))

    questions = Question.objects.filter(pk__in=question_ids)
    correct_answers = 0
    results_data = []

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

            elif question.question_type.startswith('주관식'):
                # 주관식 (단일/복수 모두 처리)
                possible_answers = question.choice_set.filter(is_correct=True).values_list('choice_text', flat=True)
                user_text = user_answer if user_answer else ""
                short_answer_text = user_text
                
                # 정답 중 하나라도 일치하면 정답 처리 (대소문자 무시)
                for answer in possible_answers:
                    if user_text.strip().lower() == answer.strip().lower():
                        is_correct = True
                        break
                        
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
    
    total_questions = len(question_ids)
    score = int((correct_answers / total_questions) * 100) if total_questions > 0 else 0
    is_pass = (score >= 80)
    
    test_result = TestResult.objects.create(
        user=request.user,
        quiz=attempt.quiz,
        score=score,
        attempt=attempt,
        is_pass=is_pass
    )

    # [뱃지 부여 함수 호출]
    award_badges(request.user, test_result)

    for result in results_data:
        if result['selected_choice'] or (result['short_answer_text'] is not None):
            UserAnswer.objects.create(
                test_result=test_result,
                question=result['question'],
                selected_choice=result['selected_choice'],
                short_answer_text=result['short_answer_text'],
                is_correct=result['is_correct']
            )

    if attempt:
        attempt.status = '완료됨'
        attempt.save()

    profile.refresh_from_db()
    badges_after = set(profile.badges.values_list('id', flat=True))
    new_badge_ids = badges_after - badges_before
    newly_awarded_badges = Badge.objects.filter(id__in=new_badge_ids)

    if not test_result.is_pass:
        failure_count = TestResult.objects.filter(
            user=request.user, 
            quiz=attempt.quiz, 
            is_pass=False
        ).count()
        
        if failure_count == 2:
            if hasattr(request.user, 'profile') and request.user.profile.pl and request.user.profile.pl.email:
                pl = request.user.profile.pl
                subject = f"[CBT 경고] 교육생 면담 요청: {profile.name}"
                message = (
                    f"{pl.name}님,\n\n"
                    f"귀하의 담당 교육생인 {profile.name} (사번: {profile.employee_id}, 기수: {profile.cohort.name if profile.cohort else '-'})이\n"
                    f"'{attempt.quiz.title}' 시험에서 누적 2회 불합격하였습니다.\n\n"
                    "바쁘시겠지만 PMTC로 직접 오셔서 교육생 면담 및 지도가 필요합니다.\n\n"
                    "- CBT 관리 시스템"
                )
                try:
                    send_mail(
                        subject, message,
                        os.environ.get('EMAIL_HOST_USER'),
                        [pl.email], fail_silently=False,
                    )
                except Exception as e:
                    print(f"PL 경고 메일 발송 실패: {e}")

    context = {
        'results_data': results_data,
        'score': score,
        'total_questions': total_questions,
        'correct_answers': correct_answers,
        'newly_awarded_badges': newly_awarded_badges,
        'test_result': test_result,
        'is_pass': is_pass,
    }

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
            df = pd.read_excel(excel_file).fillna('')
            
            error_count = 0
            success_count = 0

            for index, row in df.iterrows():
                q_type_excel = row['question_type']
                q_type_db = q_type_excel

                if q_type_excel == '주관식':
                    q_type_db = '주관식 (단일정답)'
                
                allowed_types = ['객관식', '다중선택', '주관식 (단일정답)', '주관식 (복수정답)']
                if q_type_db not in allowed_types:
                    messages.error(request, f"업로드 실패 (행 {index + 2}): 잘못된 유형입니다.")
                    error_count += 1
                    continue
                
                quiz, created = Quiz.objects.get_or_create(title=row['quiz_title'])
                
                question = Question.objects.create(
                    quiz=quiz,
                    question_text=row['question_text'],
                    question_type=q_type_db,
                    difficulty=row['difficulty']
                )

                if row['tags']:
                    tag_names = [tag.strip() for tag in str(row['tags']).split(',') if tag.strip()]
                    for tag_name in tag_names:
                        tag, created = Tag.objects.get_or_create(name=tag_name)
                        question.tags.add(tag)

                if q_type_db in ['객관식', '다중선택', '주관식 (복수정답)']:
                    for col in df.columns:
                        if str(col).startswith('correct_choice') and row[col]:
                            Choice.objects.create(question=question, choice_text=row[col], is_correct=True)
                    
                    if q_type_db in ['객관식', '다중선택']:
                        for col in df.columns:
                            if str(col).startswith('other_choice') and row[col]:
                                Choice.objects.create(question=question, choice_text=row[col], is_correct=False)
                
                elif q_type_db == '주관식 (단일정답)':
                    if row['correct_choice']:
                        Choice.objects.create(question=question, choice_text=row['correct_choice'], is_correct=True)

                success_count += 1
            
            if success_count > 0:
                messages.success(request, f"{success_count}개의 문제가 성공적으로 업로드되었습니다.")
            if error_count > 0:
                messages.warning(request, f"{error_count}개의 문제는 오류로 인해 건너뛰었습니다.")

        except Exception as e:
            messages.error(request, f"업로드 중 오류가 발생했습니다: {e}")

        return redirect('quiz:upload_quiz')

    return render(request, 'quiz/upload_quiz.html')

@login_required
def my_results_index(request):
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
    
    paginator = Paginator(sorted_results, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'quiz': quiz,
        'page_obj': page_obj
    }
    return render(request, 'quiz/my_results_list.html', context)

@login_required
def result_detail(request, result_id):
    result = get_object_or_404(TestResult, pk=result_id, user=request.user)
    incorrect_answers = result.useranswer_set.filter(is_correct=False)
    
    context = {
        'result': result,
        'incorrect_answers': incorrect_answers
    }
    return render(request, 'quiz/result_detail.html', context)

@login_required
def start_quiz(request, attempt_id):
    attempt = get_object_or_404(QuizAttempt, pk=attempt_id, user=request.user)

    existing_result = TestResult.objects.filter(attempt=attempt).first()
    if existing_result:
        if attempt.status != '완료됨':
            attempt.status = '완료됨'; attempt.save()
        messages.error(request, "이미 완료된 시험입니다. 결과 페이지에서 다시 확인해주세요.")
        return redirect('quiz:result_detail', result_id=existing_result.id)
        
    if attempt.status != '승인됨':
        messages.error(request, "아직 승인되지 않았거나 유효하지 않은 시험입니다.")
        return redirect('quiz:index')

    quiz = attempt.quiz
    final_questions = []

    # 1. [지정 문제 세트] 방식
    if quiz.generation_method == Quiz.GenerationMethod.FIXED and quiz.exam_sheet:
        final_questions = list(quiz.exam_sheet.questions.all())
    
    # 2. [태그 조합 랜덤] & 3. [일반 랜덤] (로직 통합)
    else:
        target_tags = None
        
        # (A) 태그 모드인 경우: 태그에 맞는 문제만 가져옴
        if quiz.generation_method == Quiz.GenerationMethod.TAG_RANDOM:
            target_tags = quiz.required_tags.all()
            if not target_tags.exists():
                 messages.error(request, "설정된 태그가 없습니다. 관리자에게 문의하세요.")
                 return redirect('quiz:index')
            
            # 태그별 균등 분배를 위해 태그 리스트를 순회
            loop_targets = list(target_tags)
            total_slots = 25
        
        # (B) 일반 모드인 경우: 전체 문제를 대상으로 함 (마치 '전체'라는 태그 1개가 있는 것처럼 처리)
        else:
            loop_targets = ['ALL'] # 더미 루프 1회
            total_slots = 25

        # === 공통 분배 로직 시작 ===
        count = len(loop_targets)
        base_quota = total_slots // count
        remainder = total_slots % count

        for i, target in enumerate(loop_targets):
            # 1. 이번 루프에서 뽑아야 할 총 개수 (할당량)
            this_quota = base_quota + (1 if i < remainder else 0)

            # 2. 문제 풀(Pool) 가져오기
            if target == 'ALL':
                # 일반 랜덤: 퀴즈에 연결된 모든 문제
                base_qs = quiz.question_set.all()
            else:
                # 태그 랜덤: 해당 태그가 있는 문제
                base_qs = Question.objects.filter(tags=target)

            pool_h = list(base_qs.filter(difficulty='상'))
            pool_m = list(base_qs.filter(difficulty='중'))
            pool_l = list(base_qs.filter(difficulty='하'))
            
            random.shuffle(pool_h)
            random.shuffle(pool_m)
            random.shuffle(pool_l)

            # 3. 난이도별 목표 개수 (상:32%, 하:32%, 중:나머지)
            target_h = int(this_quota * 0.32) # 약 8개
            target_l = int(this_quota * 0.32) # 약 8개
            target_m = this_quota - target_h - target_l # 약 9개

            selected_in_loop = []

            # --- [핵심] 난이도 대체(Fallback) 로직 ---
            
            # A. [상] 뽑기
            picked_h = pool_h[:target_h]
            selected_in_loop.extend(picked_h)
            missing_h = target_h - len(picked_h)
            
            # [상] 부족하면 -> [중] 목표량 증가
            target_m += missing_h 

            # B. [하] 뽑기
            picked_l = pool_l[:target_l]
            selected_in_loop.extend(picked_l)
            missing_l = target_l - len(picked_l)

            # [하] 부족하면 -> [중] 목표량 증가
            target_m += missing_l

            # C. [중] 뽑기 (상, 하에서 부족한 것까지 포함됨)
            picked_m = pool_m[:target_m]
            selected_in_loop.extend(picked_m)
            missing_m = target_m - len(picked_m)

            # [중] 부족하면 -> [하] 남은 것에서 대체
            if missing_m > 0:
                remaining_l = pool_l[len(picked_l):]
                fallback_l = remaining_l[:missing_m]
                selected_in_loop.extend(fallback_l)
                
                # 그래도 부족하면 -> [상] 남은 것에서 대체
                still_missing = missing_m - len(fallback_l)
                if still_missing > 0:
                    remaining_h = pool_h[len(picked_h):]
                    fallback_h = remaining_h[:still_missing]
                    selected_in_loop.extend(fallback_h)
            
            final_questions.extend(selected_in_loop)
            
        # (4) 최종 안전장치: 특정 태그에 문제가 너무 적어서 25개가 안 찼을 경우
        # 태그 구분 없이(혹은 전체 풀에서) 부족한 만큼 채움
        if len(final_questions) < 25:
            needed = 25 - len(final_questions)
            current_ids = [q.id for q in final_questions]
            
            # 퀴즈에 속한 모든 문제 중 아직 안 뽑힌 것
            if quiz.generation_method == Quiz.GenerationMethod.TAG_RANDOM:
                # 태그 모드였다면 해당 태그들 내에서 검색
                extra_pool = list(Question.objects.filter(tags__in=target_tags).exclude(id__in=current_ids).distinct())
            else:
                # 일반 모드라면 전체에서 검색
                extra_pool = list(quiz.question_set.exclude(id__in=current_ids))
            
            random.shuffle(extra_pool)
            final_questions.extend(extra_pool[:needed])

    # 최종 섞기
    random.shuffle(final_questions)
    
    if not final_questions:
        messages.error(request, "출제할 문제가 없습니다. (문제 부족)")
        return redirect('quiz:index')

    request.session['quiz_questions'] = [q.id for q in final_questions]
    request.session['user_answers'] = {}
    request.session['attempt_id'] = attempt.id

    return HttpResponseRedirect(reverse('quiz:take_quiz', args=(1,)))

@login_required
def submit_quiz(request):
    attempt_id = request.session.get('attempt_id')
    if attempt_id:
        attempt = QuizAttempt.objects.get(pk=attempt_id)
        if attempt.status != '완료됨':
            attempt.status = '완료됨'
            attempt.save()
    return redirect('quiz:quiz_results')

@login_required
def my_incorrect_answers_index(request):
    if not request.user.is_staff:
        messages.error(request, "접근 권한이 없습니다. (관리자 전용)")
        return redirect('quiz:index') # 또는 'dashboard'
    
    incorrect_answers = UserAnswer.objects.filter(test_result__user=request.user, is_correct=False)
    quizzes_with_incorrects = Quiz.objects.filter(question__useranswer__in=incorrect_answers).distinct()
    context = {'quizzes_with_incorrects': quizzes_with_incorrects}
    return render(request, 'quiz/my_incorrect_answers_index.html', context)

@login_required
def my_incorrect_answers_by_quiz(request, quiz_id):
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    incorrect_answers = UserAnswer.objects.filter(
        test_result__user=request.user, 
        question__quiz=quiz,
        is_correct=False
    )
    incorrect_question_ids = incorrect_answers.values_list('question', flat=True).distinct()
    incorrect_questions = Question.objects.filter(pk__in=incorrect_question_ids)
    context = {'quiz': quiz, 'incorrect_questions': incorrect_questions}
    return render(request, 'quiz/incorrect_answers_list.html', context)

@login_required
def dashboard(request):
    if not request.user.is_staff:
        return redirect('quiz:index')

    # 1. [필터링 조건 가져오기]
    selected_cohort = request.GET.get('cohort')
    selected_company = request.GET.get('company')
    selected_process = request.GET.get('process')
    selected_quiz = request.GET.get('quiz')
    selected_student = request.GET.get('student')

    # 2. [Base QuerySet]
    results = TestResult.objects.select_related('user__profile', 'quiz')
    profiles = Profile.objects.select_related('cohort', 'company', 'process')

    # 3. [필터 적용]
    if selected_cohort:
        results = results.filter(user__profile__cohort_id=selected_cohort)
        profiles = profiles.filter(cohort_id=selected_cohort)
    
    if selected_company:
        results = results.filter(user__profile__company_id=selected_company)
        profiles = profiles.filter(company_id=selected_company)

    if selected_process:
        results = results.filter(user__profile__process_id=selected_process)
        profiles = profiles.filter(process_id=selected_process)

    if selected_quiz:
        results = results.filter(quiz_id=selected_quiz)

    if selected_student:
        results = results.filter(user__profile__id=selected_student)
        profiles = profiles.filter(id=selected_student)

    # 4. [KPI 계산]
    total_students_filtered = profiles.count()
    total_attempts = results.count()
    
    if total_attempts > 0:
        avg_score = results.aggregate(Avg('score'))['score__avg']
        pass_count = results.filter(is_pass=True).count()
        pass_rate = (pass_count / total_attempts) * 100
    else:
        avg_score = 0
        pass_rate = 0

    # ---------------------------------------------------------
    # 5. [심층 분석] (모든 문제 표시 + 오답률 계산) - 수정됨
    # ---------------------------------------------------------
    
    # (1) 필터링된 결과(results)에 포함된 모든 사용자 답안을 가져옵니다.
    filtered_answers = UserAnswer.objects.filter(test_result__in=results)

    # (2) [핵심 수정] '오답'만 추리는 게 아니라, 등장한 '모든 문제' ID를 가져옵니다.
    all_question_ids = filtered_answers.values_list('question', flat=True).distinct()

    incorrect_analysis = []
    
    for q_id in all_question_ids:
        question = Question.objects.get(pk=q_id)
        
        # 전체 시도 횟수
        q_total_attempts = filtered_answers.filter(question=question).count()
        # 오답 횟수
        q_wrong_attempts = filtered_answers.filter(question=question, is_correct=False).count()
        
        if q_total_attempts > 0:
            error_rate = (q_wrong_attempts / q_total_attempts) * 100
        else:
            error_rate = 0

        # 정답 텍스트
        correct_choices_qs = question.choice_set.filter(is_correct=True).values_list('choice_text', flat=True)
        if correct_choices_qs.exists():
            correct_answer_text = ", ".join(correct_choices_qs)
            correct_answer_list = list(correct_choices_qs)
        else:
            correct_answer_text = "정답 정보 없음"
            correct_answer_list = []

        # 분포도 (Distribution)
        distribution = filtered_answers.filter(question=question).values(
            answer_text=Case(
                When(selected_choice__isnull=False, then=F('selected_choice__choice_text')),
                default=F('short_answer_text'),
                output_field=CharField(),
            )
        ).annotate(count=Count('id')).order_by('-count')
        
        dist_labels = [d['answer_text'] if d['answer_text'] else '무응답' for d in distribution]
        dist_counts = [d['count'] for d in distribution]

        incorrect_analysis.append({
            'question_id': question.id,
            'quiz_title': question.quiz.title,
            'question_text': question.question_text,
            'difficulty': question.difficulty,
            'total': q_total_attempts,
            'wrong': q_wrong_attempts,
            'rate': round(error_rate, 1),
            'correct_answer': correct_answer_text,
            'correct_list': json.dumps(correct_answer_list),
            'dist_labels': json.dumps(dist_labels), 
            'dist_counts': json.dumps(dist_counts)
        })

    # [핵심 수정] 정렬 기준: 오답률 높은 순 -> 오답 횟수 많은 순
    incorrect_analysis.sort(key=lambda x: (x['rate'], x['wrong']), reverse=True)


    # ---------------------------------------------------------
    # 6. [위험군/개별 학생 목록] (면담 후 제거 로직 추가) - 수정됨
    # ---------------------------------------------------------
    at_risk_students = []
    for profile in profiles:
        user_results = results.filter(user=profile.user).order_by('-completed_at') # 최신순 정렬
        
        if user_results.exists():
            user_avg = user_results.aggregate(Avg('score'))['score__avg'] or 0
            fail_count = user_results.filter(is_pass=False).count()
            
            # 위험군 기준: 평균 60점 미만 OR 불합격 2회 이상
            is_risk_condition = (user_avg < 60 or fail_count >= 2)
            
            if selected_student or is_risk_condition:
                # [핵심 로직] 면담 여부 확인하여 목록에서 제외하기
                # 1. 가장 최근 시험 날짜 가져오기
                last_test_date = user_results.first().completed_at
                
                # 2. 가장 최근 면담(평가) 날짜 가져오기
                last_eval = ManagerEvaluation.objects.filter(trainee_profile=profile).order_by('-created_at').first()
                
                # 3. 면담이 최신 시험보다 나중에 이루어졌다면 -> "해결됨"으로 간주하고 목록에서 스킵
                # (단, 개별 학생 선택 시에는 무조건 보여줌)
                if not selected_student and last_eval and last_eval.created_at > last_test_date:
                    continue

                at_risk_students.append({
                    'name': profile.name,
                    'cohort': profile.cohort.name if profile.cohort else '-',
                    'process': profile.process.name if profile.process else '-',
                    'avg_score': round(user_avg, 1),
                    'fail_count': fail_count,
                    'profile_id': profile.id
                })

    # 7. [차트 데이터]
    quiz_stats = results.values('quiz__title').annotate(avg=Avg('score')).order_by('quiz__title')
    chart_labels = [item['quiz__title'] for item in quiz_stats]
    chart_data = [round(item['avg'], 1) for item in quiz_stats]

    # 8. [Context 전달]
    context = {
        'total_students': total_students_filtered,
        'total_attempts': total_attempts,
        'average_score': round(avg_score, 1) if avg_score else 0,
        'pass_rate': round(pass_rate, 1),
        
        'incorrect_analysis': incorrect_analysis,
        'at_risk_students': at_risk_students,
        'chart_labels': chart_labels,
        'chart_data': chart_data,

        'cohorts': Cohort.objects.all(),
        'companies': Company.objects.all(),
        'processes': Process.objects.all(),
        'quizzes': Quiz.objects.all(),
        'all_profiles': Profile.objects.select_related('cohort').order_by('cohort__start_date', 'name'),
        
        'sel_cohort': int(selected_cohort) if selected_cohort else '',
        'sel_company': int(selected_company) if selected_company else '',
        'sel_process': int(selected_process) if selected_process else '',
        'sel_quiz': int(selected_quiz) if selected_quiz else '',
        'sel_student': int(selected_student) if selected_student else '',
    }

    return render(request, 'quiz/dashboard.html', context)

@login_required
def personal_dashboard(request):
    profile, created = Profile.objects.get_or_create(user=request.user)
    summary_data = []
    quizzes_taken = Quiz.objects.filter(testresult__user=request.user).distinct()

    for quiz in quizzes_taken:
        results_for_quiz = TestResult.objects.filter(user=request.user, quiz=quiz)
        first_attempt = results_for_quiz.order_by('completed_at').first()
        first_score = first_attempt.score if first_attempt else None
        avg_score = results_for_quiz.aggregate(Avg('score'))['score__avg']
        max_score = results_for_quiz.aggregate(Max('score'))['score__max']
        attempts = results_for_quiz.count()

        summary_data.append({
            'title': quiz.title,
            'first_score': first_score,
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
        'user_badges': profile.badges.all(), 
    }
    return render(request, 'quiz/personal_dashboard.html', context)

@login_required
def start_group_quiz(request, quiz_id):
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    attempt = QuizAttempt.objects.create(
        user=request.user,
        quiz=quiz,
        status=QuizAttempt.Status.APPROVED,
        assignment_type=QuizAttempt.AssignmentType.GROUP
    )
    return redirect('quiz:start_quiz', attempt_id=attempt.id)

@login_required
def export_student_data(request):
    if not request.user.is_staff:
        return redirect('quiz:index')

    profiles = Profile.objects.select_related(
        'user', 'cohort', 'company', 'process', 'pl'
    ).prefetch_related(
        'user__testresult_set', 
        'badges',               
        'managerevaluation_set' 
    ).order_by('cohort__start_date', 'user__username')

    all_quizzes = Quiz.objects.all().order_by('title')

    data_list = []

    for profile in profiles:
        cohort_name = profile.cohort.name if profile.cohort else '-'
        company_name = profile.company.name if profile.company else '-'
        process_name = profile.process.name if profile.process else '-'
        pl_name = profile.pl.name if profile.pl else '-'
        
        test_results = list(profile.user.testresult_set.all()) 
        
        total_tests = len(test_results)
        
        if total_tests > 0:
            scores = [r.score for r in test_results]
            avg_score = sum(scores) / total_tests
            max_score = max(scores)
            pass_count = sum(1 for r in test_results if r.is_pass)
            fail_count = total_tests - pass_count
            test_results.sort(key=lambda x: x.completed_at) 
            last_test_date = test_results[-1].completed_at.strftime('%Y-%m-%d')
        else:
            avg_score = 0
            max_score = 0
            pass_count = 0
            fail_count = 0
            last_test_date = '-'

        first_scores_map = {} 
        for res in test_results:
            if res.quiz_id not in first_scores_map:
                first_scores_map[res.quiz_id] = res.score

        badge_count = profile.badges.count()
        badge_list = ", ".join([b.name for b in profile.badges.all()])

        last_evaluation = profile.managerevaluation_set.order_by('-created_at').first()
        eval_manager = last_evaluation.manager.username if last_evaluation and last_evaluation.manager else '-'
        eval_comment = last_evaluation.overall_comment if last_evaluation else '평가 없음'
        
        row_data = {
            '사용자 ID': profile.user.username,
            '이름': profile.name,
            '이메일': profile.user.email,
            '사번': profile.employee_id,
            '기수': cohort_name,
            '소속 회사': company_name,
            '공정': process_name,
            '담당 PL': pl_name,
            '프로필 완성 여부': "완료" if profile.is_profile_complete else "미완료",
            '총 응시 횟수': total_tests,
            '평균 점수': round(avg_score, 1) if avg_score else 0,
            '최고 점수': max_score,
            '합격 횟수': pass_count,
            '불합격 횟수': fail_count,
            '최근 응시일': last_test_date,
        }

        for quiz in all_quizzes:
            col_name = f"[{quiz.title}] 1차 점수"
            score = first_scores_map.get(quiz.id)
            row_data[col_name] = score if score is not None else '-'

        row_data.update({
            '획득 뱃지 수': badge_count,
            '뱃지 목록': badge_list,
            '평가 담당자': eval_manager,
            '매니저 종합 의견': eval_comment,
            'AI 요약': profile.ai_summary if profile.ai_summary else '-'
        })

        data_list.append(row_data)

    df = pd.DataFrame(data_list)

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    filename = f"trainee_full_data_{timezone.now().strftime('%Y%m%d')}.xlsx"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    df.to_excel(response, index=False)

    return response

@login_required
def evaluate_trainee(request, profile_id):
    if not request.user.is_staff:
        messages.error(request, "접근 권한이 없습니다.")
        return redirect('quiz:index')

    trainee = get_object_or_404(Profile, pk=profile_id)

    common_quizzes = Quiz.objects.filter(category=Quiz.Category.COMMON)
    process_quizzes = Quiz.objects.filter(
        category=Quiz.Category.PROCESS, 
        associated_process=trainee.process
    )
    required_quizzes = common_quizzes | process_quizzes
    
    passed_quiz_ids = set(TestResult.objects.filter(
        user=trainee.user, 
        is_pass=True
    ).values_list('quiz_id', flat=True))

    required_quiz_ids = set(required_quizzes.values_list('id', flat=True))
    is_all_passed = required_quiz_ids.issubset(passed_quiz_ids)

    existing_evaluation = ManagerEvaluation.objects.filter(trainee_profile=trainee).first()

    if request.method == 'POST':
        form = EvaluationForm(request.POST, instance=existing_evaluation)
        if form.is_valid():
            evaluation = form.save(commit=False)
            evaluation.manager = request.user
            evaluation.trainee_profile = trainee
            evaluation.save()
            form.save_m2m() 
            
            messages.success(request, f"{trainee.name} 님에 대한 평가가 저장되었습니다.")
            return redirect('quiz:dashboard') 
    else:
        form = EvaluationForm(instance=existing_evaluation)

    categories = EvaluationCategory.objects.prefetch_related('evaluationitem_set').order_by('order')

    context = {
        'trainee': trainee,
        'form': form,
        'categories': categories,
        'is_all_passed': is_all_passed,
    }
    return render(request, 'quiz/evaluate_trainee.html', context)


def award_badges(user, test_result):
    try:
        user_profile = user.profile
        user_badges = user_profile.badges.all()
        user_badge_names = set(user_badges.values_list('name', flat=True))
    except Profile.DoesNotExist:
        return
    except Exception as e:
        print(f"뱃지 로직 오류 (프로필 로드 실패): {e}")
        return

    badges_to_add = []
    all_badges = {badge.name: badge for badge in Badge.objects.all()}

    # [1] 첫걸음
    badge_name = '첫걸음'
    if badge_name not in user_badge_names:
        if TestResult.objects.filter(user=user).count() == 1:
            if all_badges.get(badge_name):
                badges_to_add.append(all_badges[badge_name])
                user_badge_names.add(badge_name)

    # [2] 퍼펙트
    badge_name = '퍼펙트'
    if test_result.score == 100 and badge_name not in user_badge_names:
        if all_badges.get(badge_name):
            badges_to_add.append(all_badges[badge_name])
            user_badge_names.add(badge_name)

    # [3] 완벽한 시작
    badge_name = '완벽한 시작'
    if test_result.score == 100 and badge_name not in user_badge_names:
        previous_100s = TestResult.objects.filter(
            user=user, score=100
        ).exclude(pk=test_result.pk).exists()
        if not previous_100s:
            if all_badges.get(badge_name):
                badges_to_add.append(all_badges[badge_name])
                user_badge_names.add(badge_name)

    # [4] 지니어스
    badge_name = '지니어스'
    if test_result.score >= 90 and badge_name not in user_badge_names:
        quiz_has_hard_questions = test_result.quiz.question_set.filter(difficulty='상').exists()
        if quiz_has_hard_questions:
            if all_badges.get(badge_name):
                badges_to_add.append(all_badges[badge_name])
                user_badge_names.add(badge_name)

    # [5] 아차상
    badge_name = '아차상'
    if (test_result.score == 98 or test_result.score == 99) and badge_name not in user_badge_names:
        if all_badges.get(badge_name):
            badges_to_add.append(all_badges[badge_name])
            user_badge_names.add(badge_name)

    # [6] 아슬아슬
    badge_name = '아슬아슬'
    if 60 <= test_result.score <= 65 and badge_name not in user_badge_names:
        if all_badges.get(badge_name):
            badges_to_add.append(all_badges[badge_name])
            user_badge_names.add(badge_name)

    # [7] 절반의 성공
    badge_name = '절반의 성공'
    if test_result.score == 50 and badge_name not in user_badge_names:
        if all_badges.get(badge_name):
            badges_to_add.append(all_badges[badge_name])
            user_badge_names.add(badge_name)

    # [8] 괜찮아, 다시 하면 돼
    badge_name = '괜찮아, 다시 하면 돼'
    if test_result.score <= 30 and badge_name not in user_badge_names:
        if all_badges.get(badge_name):
            badges_to_add.append(all_badges[badge_name])
            user_badge_names.add(badge_name)

    # [9] 빵점...?!
    badge_name = '빵점...?!'
    if test_result.score == 0 and badge_name not in user_badge_names:
        if all_badges.get(badge_name):
            badges_to_add.append(all_badges[badge_name])
            user_badge_names.add(badge_name)

    # [10] 재도전자
    badge_name = '재도전자'
    if badge_name not in user_badge_names:
        attempts_count = TestResult.objects.filter(
            user=user, quiz=test_result.quiz
        ).count()
        if attempts_count >= 3:
            if all_badges.get(badge_name):
                badges_to_add.append(all_badges[badge_name])
                user_badge_names.add(badge_name)

    # [11] 성실한 응시자
    badge_name = '성실한 응시자'
    if badge_name not in user_badge_names:
        total_attempts = TestResult.objects.filter(user=user).count()
        if total_attempts >= 10:
            if all_badges.get(badge_name):
                badges_to_add.append(all_badges[badge_name])
                user_badge_names.add(badge_name)

    # [12] 연승가도
    badge_name = '연승가도'
    if test_result.is_pass and badge_name not in user_badge_names:
        last_three_results = TestResult.objects.filter(user=user).order_by('-completed_at')[:3]
        if len(last_three_results) == 3 and all(r.is_pass for r in last_three_results):
            if all_badges.get(badge_name):
                badges_to_add.append(all_badges[badge_name])
                user_badge_names.add(badge_name)

    # [13] 불사조
    badge_name = '불사조'
    if test_result.is_pass and badge_name not in user_badge_names:
        had_failed_before = TestResult.objects.filter(
            user=user, quiz=test_result.quiz, is_pass=False
        ).exists()
        if had_failed_before:
             if all_badges.get(badge_name):
                badges_to_add.append(all_badges[badge_name])
                user_badge_names.add(badge_name)

    # [14] 노력의 결실
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

    # [15] 정복자
    badge_name = '정복자'
    if badge_name not in user_badge_names:
        all_quiz_ids = set(Quiz.objects.values_list('id', flat=True))
        attempted_quiz_ids = set(TestResult.objects.filter(user=user).values_list('quiz_id', flat=True).distinct())
        
        if all_quiz_ids and all_quiz_ids.issubset(attempted_quiz_ids):
            if all_badges.get(badge_name):
                badges_to_add.append(all_badges[badge_name])
                user_badge_names.add(badge_name)

    # [16] all 100
    badge_name = 'all 100'
    if test_result.score == 100 and badge_name not in user_badge_names:
        all_quiz_ids = set(Quiz.objects.values_list('id', flat=True))
        passed_100_quiz_ids = set(TestResult.objects.filter(user=user, score=100).values_list('quiz_id', flat=True).distinct())

        if all_quiz_ids and all_quiz_ids.issubset(passed_100_quiz_ids):
            if all_badges.get(badge_name):
                badges_to_add.append(all_badges[badge_name])
                user_badge_names.add(badge_name)

    # [17] 공정 마스터
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

    # [18] 꾸준함
    badge_name = '꾸준함'
    if badge_name not in user_badge_names:
        recent_test_dates = list(TestResult.objects.filter(user=user).dates('completed_at', 'day', order='DESC')[:3])
        if len(recent_test_dates) == 3:
            is_consecutive = (
                recent_test_dates[0] - timedelta(days=1) == recent_test_dates[1] and
                recent_test_dates[1] - timedelta(days=1) == recent_test_dates[2]
            )
            if is_consecutive:
                if all_badges.get(badge_name):
                    badges_to_add.append(all_badges[badge_name])
                    user_badge_names.add(badge_name)

    if badges_to_add:
        user_profile.badges.add(*badges_to_add)

    final_badge_count = len(user_badge_names) 
    
    # [19] 수집가
    badge_name = '수집가'
    if final_badge_count >= 5 and badge_name not in user_badge_names:
        if all_badges.get(badge_name):
            user_profile.badges.add(all_badges[badge_name])
            user_badge_names.add(badge_name)

    # [20] 뱃지 콜렉터
    badge_name = '뱃지 콜렉터'
    if final_badge_count >= 10 and badge_name not in user_badge_names:
         if all_badges.get(badge_name):
            user_profile.badges.add(all_badges[badge_name])
            user_badge_names.add(badge_name)