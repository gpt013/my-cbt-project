import json
import random
import pandas as pd
import os
from datetime import timedelta
from django.core.mail import EmailMessage
from io import BytesIO
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
from accounts.models import StudentLog # 상단 import 확인 필수!
from django.forms import inlineformset_factory
# [핵심] 데이터 분석 및 집계를 위한 필수 모듈 (누락된 부분 추가됨)
from django.db.models import Avg, Count, Q, Max,Min, F, Case, When, Value, CharField, Window
from attendance.models import DailySchedule
from django.db.models.functions import DenseRank, Coalesce
from .utils import calculate_tag_stats

# accounts 앱의 모델들
from accounts.models import (
    Profile, Badge, EvaluationRecord, EvaluationCategory, 
    ManagerEvaluation, Cohort, Company, Process, ProcessAccessRequest, FinalAssessment, PartLeader,Profile, StudentLog
)

# quiz 앱의 모델들
from .models import (
    Quiz, Question, Choice, TestResult, UserAnswer, 
    QuizAttempt, ExamSheet, Tag
)

# 폼
from .forms import EvaluationForm, TraineeFilterForm, QuizForm, QuestionForm, StudentLogForm

def is_process_manager(user, target_profile):
    """
    요청자(user)가 관리자(Superuser)이거나, 
    대상 교육생(target_profile)과 '같은 공정의 매니저(교수)'인지 확인합니다.
    """
    # 1. 최고 관리자는 프리패스
    if user.is_superuser:
        return True
    
    # 2. 매니저(교수)인 경우: 본인의 공정과 학생의 공정이 같은지 확인
    if hasattr(user, 'profile') and user.profile.is_manager:
        if user.profile.process == target_profile.process:
            return True
            
    return False

# 1. '마이 페이지'
@login_required
def my_page(request):
    user = request.user
    
    # 1. 프로필 가져오기
    # (Signal이 있어서 보통 user.profile로 접근 가능하지만, 안전하게 get_or_create 사용)
    profile, created = Profile.objects.get_or_create(user=user)

    # 2. 진행 중인 시험 (대기/승인)
    pending_attempts = QuizAttempt.objects.filter(
        user=user, 
        status__in=['대기중', '승인됨']
    )

    # 3. [핵심 수정] 최근 시험 결과 + 면담 상태 확인 로직
    # (최신순 3개만 가져와서 가공합니다)
    raw_results = TestResult.objects.filter(user=user).select_related('quiz').order_by('-completed_at')[:3]
    enhanced_results = []

    for result in raw_results:
        counseling_status = None
        
        # 불합격(80점 미만)인 경우 면담 상태 체크
        if not result.is_pass:
            # StudentLog에서 해당 시험 제목이 포함된 '면담' 기록이 있는지 확인
            # (예: "[반도체 공정] 시험 불합격..." 같은 내용이 있는지)
            has_counseling_log = StudentLog.objects.filter(
                profile=profile,
                log_type='counseling',
                reason__contains=result.quiz.title 
            ).exists()

            if has_counseling_log:
                counseling_status = '완료'
            else:
                counseling_status = '예정'
        
        # 결과 객체와 상태를 묶어서 리스트에 추가
        enhanced_results.append({
            'result': result,
            'counseling_status': counseling_status
        })

    # 4. 뱃지 및 평가 피드백
    latest_badges = profile.badges.all().order_by('-id')[:3]
    
    # 평가 피드백 (경고, 칭찬, 면담 기록만 표시)
    latest_evaluations = StudentLog.objects.filter(
        profile=profile,
        log_type__in=['warning', 'compliment', 'counseling']
    ).order_by('-created_at')[:3]
    
    context = {
        'profile': profile,
        'pending_attempts': pending_attempts,
        'enhanced_results': enhanced_results, # [중요] 템플릿에서 이 이름으로 씁니다
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
    # [2] 권한 필터 설정 (사용자 그룹/개인 권한)
    # -------------------------------------------------------
    if user.is_staff:
        permission_query = Q()
    else:
        # 내 그룹이나 아이디가 포함된 시험 (특별 할당된 경우)
        permission_query = Q(allowed_groups__in=user_groups) | Q(allowed_users=user)

    # -------------------------------------------------------
    # [3] '나의 공정' 퀴즈 목록
    # -------------------------------------------------------
    # 조건: (공정이 내 공정과 일치) OR (특별히 나에게 할당된 시험)
    if user.is_staff:
        # 관리자는 모든 공정 시험을 '나의 공정' 탭에서 볼 수 있게 함 (또는 본인 공정만 보게 수정 가능)
        my_process_quizzes_list = Quiz.objects.filter(
            category=Quiz.Category.PROCESS
        ).distinct()
    else:
        # 교육생: 내 공정 시험 + 특별 권한 받은 시험
        my_process_quizzes_list = Quiz.objects.filter(
            Q(category=Quiz.Category.PROCESS) & 
            (Q(associated_process=user_process) | permission_query)
        ).distinct()

    # -------------------------------------------------------
    # [4] '기타 공정' 퀴즈 목록
    # -------------------------------------------------------
    # 조건: 공정 시험이면서, '나의 공정' 리스트에 없는 나머지 모든 시험
    # (이렇게 해야 타 공정 시험이 화면에 보이고, '요청' 버튼을 누를 수 있습니다)
    
    if user.is_staff:
        other_process_quizzes_list = Quiz.objects.none()
    else:
        other_process_quizzes_list = Quiz.objects.filter(
            category=Quiz.Category.PROCESS
        ).exclude(
            id__in=my_process_quizzes_list.values('id')
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
            tags_str = str(row[3] or '').strip()
            
            # 정답 값 (쉼표로 분리하여 리스트로 만듦)
            answer_raw = str(row[8] or '').strip()
            # 예: "1, 3" -> ['1', '3'], "에칭기" -> ['에칭기']
            answer_list = [a.strip() for a in answer_raw.split(',')]

            # 문제 생성
            new_question = Question.objects.create(
                quiz=target_quiz,
                question_text=question_text,
                question_type=q_type,
                difficulty=difficulty
            )

            if tags_str:
                for tag_name in tags_str.split(','):
                    if tag_name.strip():
                        tag, _ = Tag.objects.get_or_create(name=tag_name.strip())
                        new_question.tags.add(tag)

            # --- [핵심] 정답 처리 로직 (복수 정답 지원) ---
            
            # (A) 주관식 (단일/복수 모두 쉼표로 구분해서 저장)
            if '주관식' in q_type:
                if answer_raw:
                    # 주관식 복수 정답은 하나의 Choice에 몰아넣지 않고, 여러 Choice를 정답으로 등록하거나
                    # 편의상 쉼표로 구분된 텍스트 자체를 정답 처리할 수도 있습니다.
                    # 여기서는 '복수 정답' 타입이라면 각각을 정답 보기로 등록합니다.
                    for ans in answer_list:
                        Choice.objects.create(
                            question=new_question,
                            choice_text=ans,
                            is_correct=True
                        )
            
            # (B) 객관식/다중선택
            else:
                choices_raw = [row[4], row[5], row[6], row[7]]
                
                has_correct_marked = False

                for i, choice_text in enumerate(choices_raw):
                    choice_text = str(choice_text or '').strip()
                    
                    if choice_text:
                        is_correct = False
                        
                        # 1. 번호 매칭 (예: 정답칸에 '1,3' -> 인덱스 0, 2번이 정답)
                        # 현재 보기 번호(1~4)가 정답 리스트에 들어있는지 확인
                        if str(i + 1) in answer_list:
                            is_correct = True
                            
                        # 2. 텍스트 매칭 (예: 정답칸에 '사과,배' -> 보기가 '사과'면 정답)
                        elif choice_text in answer_list:
                            is_correct = True
                        
                        Choice.objects.create(
                            question=new_question,
                            choice_text=choice_text,
                            is_correct=is_correct
                        )
                        
                        if is_correct: has_correct_marked = True
                
                # (안전장치) 번호/텍스트 매칭 실패 시 입력값을 그대로 정답 보기로 추가
                if not has_correct_marked and answer_raw:
                     # 다중선택인데 매칭 안된 경우, 쉼표로 연결된 전체를 하나의 보기로 넣지 않고 경고하거나
                     # 여기서는 단순하게 첫 번째 값만이라도 추가합니다.
                     pass 

            success_count += 1

        return JsonResponse({'status': 'success', 'count': success_count})

    except Exception as e:
        print(e) # 디버깅용
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

    if not test_result.is_pass:
        # 현재 시험 포함해서 불합격 횟수 조회
        fail_count = TestResult.objects.filter(
            user=request.user, 
            quiz=attempt.quiz, 
            is_pass=False
        ).count()
        
        # 3회 이상이면 잠금(Lock)
        if fail_count >= 3:
            # 프로필 상태를 'counseling'(면담필요)로 변경
            request.user.profile.status = 'counseling' 
            request.user.profile.save()
            messages.warning(request, "⛔ 3회 불합격하여 계정이 '면담 필요' 상태로 전환되었습니다. 추가 응시가 제한됩니다.")

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
        # [기존 로직] 불합격 횟수 카운트
        failure_count = TestResult.objects.filter(
            user=request.user, 
            quiz=attempt.quiz, 
            is_pass=False
        ).count()
        
        if failure_count == 2:
            # 1. 불합격 기록 2건을 시간 순서대로 가져옵니다.
            failed_attempts = TestResult.objects.filter(
                user=request.user, 
                quiz=attempt.quiz, 
                is_pass=False
            ).order_by('completed_at')

            if failed_attempts.count() >= 2:
                first_fail_data = failed_attempts[0]
                second_fail_data = failed_attempts[1]
                
                # 날짜와 점수 포맷팅 (YYYY-MM-DD HH:MM / 90점)
                date_format = '%Y-%m-%d %H:%M'
                data_1 = f"{first_fail_data.completed_at.strftime(date_format)} / {first_fail_data.score}점"
                data_2 = f"{second_fail_data.completed_at.strftime(date_format)} / {second_fail_data.score}점"

                if hasattr(request.user, 'profile') and request.user.profile.pl and request.user.profile.pl.email:
                    # 'profile'은 이미 함수 내에서 정의되어 있습니다.
                    pl = request.user.profile.pl
                    subject = f"[CBT 경고] 교육생 면담 요청: {profile.name}"
                    
                    # 2. 메일 내용에 상세 점수 정보를 추가합니다.
                    message = (
                        f"{pl.name}님,\n\n"
                        f"귀하의 담당 교육생인 {profile.name} (사번: {profile.employee_id}, 기수: {profile.cohort.name if profile.cohort else '-'})이\n"
                        f"'{attempt.quiz.title}' 시험에서 누적 2회 불합격하였습니다.\n\n"
                        f"--- 불합격 상세 정보 ---\n"
                        f"1차 불합격: {data_1}\n"
                        f"2차 불합격: {data_2}\n"
                        f"------------------------\n\n"
                        "바쁘시겠지만 PMTC로 직접 오셔서 교육생 면담 및 지도가 필요합니다.\n\n"
                        f"- CBT 관리 시스템"
                    )
                    
                    # 3. 메일 발송
                    try:
                        send_mail(
                            subject, message,
                            os.environ.get('EMAIL_HOST_USER'),
                            [pl.email], fail_silently=False,
                        )
                    except Exception as e:
                        print(f"PL 경고 메일 발송 실패: {e}")

    # 최종 Context 및 세션 정리
    context = {
        'results_data': results_data,
        'score': score,
        'total_questions': total_questions,
        'correct_answers': correct_answers,
        'newly_awarded_badges': newly_awarded_badges,
        'test_result': test_result,
        'is_pass': is_pass,
    }

    # 세션 데이터 정리
    request.session.pop('quiz_questions', None)
    request.session.pop('user_answers', None)
    request.session.pop('attempt_id', None)

    # 함수 최종 종료
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
    
    if not request.user.is_staff:
        messages.error(request, "보안 정책상 상세 문항 확인은 제한됩니다. (점수만 확인 가능)")
        return redirect('quiz:my_results_index')
    
    result = get_object_or_404(TestResult, pk=result_id, user=request.user)
    incorrect_answers = result.useranswer_set.filter(is_correct=False)
    
    context = {
        'result': result,
        'incorrect_answers': incorrect_answers
    }
    return render(request, 'quiz/result_detail.html', context)

@login_required
def start_quiz(request, attempt_id):
    # 1. 본인 확인 및 정보 가져오기
    attempt = get_object_or_404(QuizAttempt, pk=attempt_id, user=request.user)
    quiz = attempt.quiz
    profile = request.user.profile

    # ----------------------------------------------------------
    # [Step 3 핵심] 계정 잠금(Lock) 및 3차 제한 검사
    # ----------------------------------------------------------
    
    # (1) 이미 잠긴 계정인지 확인 ('면담필요' 또는 '퇴소' 상태)
    if profile.status in ['counseling', 'dropout']:
        messages.error(request, "⛔ 계정이 잠겨있어 시험을 시작할 수 없습니다. 매니저 면담이 필요합니다.")
        return redirect('quiz:index')

    # (2) 3차 탈락 여부 확인 (현재 시험 기준)
    fail_count = TestResult.objects.filter(user=request.user, quiz=quiz, is_pass=False).count()
    
    if fail_count >= 3:
        # 상태를 강제로 '면담필요'로 변경하고 잠금
        if profile.status == 'attending':
            profile.status = 'counseling'
            profile.save()
        
        messages.error(request, f"⛔ '{quiz.title}' 시험에 3회 불합격하여 응시가 제한됩니다. 매니저 면담 후 해제 가능합니다.")
        return redirect('quiz:index')

    # ----------------------------------------------------------

    # (3) 기존 로직: 이미 완료된 시험인지 확인
    existing_result = TestResult.objects.filter(attempt=attempt).first()
    if existing_result:
        if attempt.status != '완료됨':
            attempt.status = '완료됨'
            attempt.save()
        messages.error(request, "이미 완료된 시험입니다. 결과 페이지에서 다시 확인해주세요.")
        return redirect('quiz:result_detail', result_id=existing_result.id)
        
    # (4) 승인 상태 확인
    if attempt.status != '승인됨':
        messages.error(request, "아직 승인되지 않았거나 유효하지 않은 시험입니다.")
        return redirect('quiz:index')

    # ----------------------------------------------------------
    # [문제 출제 로직 시작]
    # ----------------------------------------------------------
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
        
        # (B) 일반 모드인 경우: 전체 문제를 대상으로 함
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
                base_qs = quiz.question_set.all()
            else:
                base_qs = Question.objects.filter(tags=target)

            pool_h = list(base_qs.filter(difficulty='상'))
            pool_m = list(base_qs.filter(difficulty='중'))
            pool_l = list(base_qs.filter(difficulty='하'))
            
            random.shuffle(pool_h)
            random.shuffle(pool_m)
            random.shuffle(pool_l)

            # 3. 난이도별 목표 개수 (상:32%, 하:32%, 중:나머지)
            target_h = int(this_quota * 0.32) 
            target_l = int(this_quota * 0.32) 
            target_m = this_quota - target_h - target_l 

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
            
        # (4) 최종 안전장치: 문제가 25개가 안 찼을 경우
        if len(final_questions) < 25:
            needed = 25 - len(final_questions)
            current_ids = [q.id for q in final_questions]
            
            if quiz.generation_method == Quiz.GenerationMethod.TAG_RANDOM:
                extra_pool = list(Question.objects.filter(tags__in=target_tags).exclude(id__in=current_ids).distinct())
            else:
                extra_pool = list(quiz.question_set.exclude(id__in=current_ids))
            
            random.shuffle(extra_pool)
            final_questions.extend(extra_pool[:needed])

    # 최종 섞기
    random.shuffle(final_questions)
    
    if not final_questions:
        messages.error(request, "출제할 문제가 없습니다. (문제 부족)")
        return redirect('quiz:index')

    # 세션에 문제 저장
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
def approve_attempt(request, attempt_id):
    # 1. 관리자 권한 확인
    if not request.user.is_staff:
        messages.error(request, "권한이 없습니다.")
        return redirect('quiz:dashboard')

    attempt = get_object_or_404(QuizAttempt, pk=attempt_id)
    trainee_process = attempt.user.profile.process
    
    # 2. [핵심] 매니저의 공정과 교육생의 공정 비교 (최고 관리자는 제외)
    # request.user가 최고 관리자(superuser)라면 통과, 아니라면 공정 체크
    if not is_process_manager(request.user, target_profile):
        # 교수의 공정과 학생의 공정이 다르면 거절
        messages.error(request, f"🚫 본인 담당 공정({target_profile.process})의 교육생만 승인할 수 있습니다.")
        return redirect('quiz:dashboard')

    # 3. 승인 처리
    attempt.status = '승인됨'
    attempt.save()
    messages.success(request, f"{attempt.user.profile.name}님의 시험 요청을 승인했습니다.")
    
    return redirect('quiz:dashboard')

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

    # 매니저(슈퍼유저 아님)가 자기 공정이 아닌 것을 선택했는지 확인
    if not request.user.is_superuser and hasattr(request.user, 'profile') and request.user.profile.process:
        my_process_id = str(request.user.profile.process.id)
        
        # 1. 전체 승인 티켓이 있는지 확인 (최강 권한)
        has_global_ticket = ProcessAccessRequest.objects.filter(
            requester=request.user,
            target_process__isnull=True, # 전체 공정 티켓
            status='approved'
        ).exists()

        if not selected_process:
            # 전체 보기를 원하는데, 전체 티켓이 없으면 -> 내 공정으로 강제
            if not has_global_ticket:
                selected_process = my_process_id
        
        elif str(selected_process) != my_process_id:
            # 타 공정을 선택했는데
            # 1. 전체 티켓이 있거나 OR 2. 해당 공정 티켓이 있으면 통과
            has_specific_ticket = ProcessAccessRequest.objects.filter(
                requester=request.user,
                target_process_id=selected_process,
                status='approved'
            ).exists()

            if not (has_global_ticket or has_specific_ticket):
                messages.error(request, "⛔ 조회 권한이 없습니다.")
                selected_process = my_process_id

    # 2. [Base QuerySet]
    results = TestResult.objects.select_related('user__profile', 'quiz')
    profiles = Profile.objects.select_related('cohort', 'company', 'process')

    # 조건: 슈퍼유저 아니고 AND 매니저 권한 없고 AND PL 권한 없는 사람만 조회
    exclude_staff_condition = Q(user__is_superuser=False) & Q(is_manager=False) & Q(is_pl=False)

    profiles = profiles.filter(exclude_staff_condition)
    # 결과 데이터도 위에서 걸러진 '순수 교육생'들의 결과만 남김
    results = results.filter(user__profile__in=profiles)

    if not request.user.is_superuser:
        # 매니저의 공정 확인
        if hasattr(request.user, 'profile') and request.user.profile.process:
            my_process = request.user.profile.process
            
            # 결과와 프로필을 내 공정으로만 한정
            results = results.filter(user__profile__process=my_process)
            profiles = profiles.filter(process=my_process)
            
            # (선택사항) 필터 드롭다운에서도 타 공정 숨기기
            processes = Process.objects.filter(id=my_process.id)
        else:
            # 공정이 없는 매니저는 아무것도 못 보게 하거나, 예외 처리
            messages.warning(request, "매니저님의 공정 정보가 설정되지 않아 데이터를 볼 수 없습니다.")
            results = results.none()
            profiles = profiles.none()

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
    
    # [추가 검문소] (기존에 추가한 타 공정 차단 로직 유지)
    if not request.user.is_superuser and hasattr(request.user, 'profile') and request.user.profile.process:
        my_process_id = str(request.user.profile.process.id)
        # (전체 티켓 확인 로직 등 기존 코드 유지...)
        has_global_ticket = ProcessAccessRequest.objects.filter(
            requester=request.user, target_process__isnull=True, status='approved'
        ).exists()

        if not selected_process:
            if not has_global_ticket: selected_process = my_process_id
        elif str(selected_process) != my_process_id:
            has_specific_ticket = ProcessAccessRequest.objects.filter(
                requester=request.user, target_process_id=selected_process, status='approved'
            ).exists()
            if not (has_global_ticket or has_specific_ticket):
                messages.error(request, "⛔ 조회 권한이 없습니다.")
                selected_process = my_process_id

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

        # 이 문제를 푼 사람들이 속한 기수 ID를 중복 없이 세어봅니다.
        distinct_cohorts_count = filtered_answers.filter(question=question).values('test_result__user__profile__cohort').distinct().count()

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

        # [수정] 난이도 조정 제안 메시지 (기준: 3개 기수 이상)
        suggestion = None
        
        if distinct_cohorts_count >= 3:  # <-- 기준 변경됨 (3명 -> 3기수)
            if error_rate < 30 and question.difficulty == '상':
                suggestion = "⬇️ 하향 추천 (너무 쉬움)"
            elif error_rate > 50 and question.difficulty == '하':
                suggestion = "⚠️ 상향 추천 (너무 어려움)"

        # (만약 기수가 부족하면 몇 기수가 풀었는지 힌트를 줄 수도 있습니다)
        # else:
        #     suggestion = f"(데이터 수집 중: 현재 {distinct_cohorts_count}개 기수 응시)"

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

    pending_requests_count = 0
    if request.user.is_superuser:
        pending_requests_count = ProcessAccessRequest.objects.filter(status='pending').count()

    context = {
        # ... (기존 컨텍스트 유지) ...
        'pending_requests_count': pending_requests_count, # 추가
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

    target_process_id = request.GET.get('process_id')
    
    # 1. 대상 프로필 조회 (권한 필터링 포함)
    profiles = Profile.objects.select_related(
        'user', 'cohort', 'company', 'process', 'pl'
    ).prefetch_related(
        'user__testresult_set', 'badges', 'managerevaluation_set', 'logs', 'dailyschedule_set'
    ).order_by('cohort__start_date', 'user__username')

    # 2. 권한 필터링
    my_process = None
    if hasattr(request.user, 'profile') and request.user.profile.process:
        my_process = request.user.profile.process

    if request.user.is_superuser:
        if target_process_id and target_process_id != 'ALL':
            profiles = profiles.filter(process_id=target_process_id)
    else:
        if not my_process:
            messages.error(request, "본인 공정 정보가 없어 작업을 수행할 수 없습니다.")
            return redirect('quiz:dashboard')

        if target_process_id == 'ALL':
            global_ticket = ProcessAccessRequest.objects.filter(
                requester=request.user, target_process__isnull=True, status='approved'
            ).first()
            if global_ticket:
                global_ticket.status = 'expired'
                global_ticket.save()
            else:
                messages.error(request, "⛔ 전체 데이터 다운로드 권한이 없습니다.")
                return redirect('quiz:dashboard')

        elif not target_process_id or str(target_process_id) == str(my_process.id):
            profiles = profiles.filter(process=my_process)
            
        else:
            access_ticket = ProcessAccessRequest.objects.filter(
                requester=request.user, target_process_id=target_process_id, status='approved'
            ).first()
            if access_ticket:
                profiles = profiles.filter(process_id=target_process_id)
                access_ticket.status = 'expired'
                access_ticket.save()
            else:
                messages.error(request, "⛔ 해당 공정 접근 권한이 없습니다.")
                return redirect('quiz:dashboard')

    # 3. 엑셀 데이터 생성
    all_quizzes = Quiz.objects.all().order_by('title')
    data_list = []

    for profile in profiles:
        # (A) 기본 정보
        row_data = {
            '사용자 ID': profile.user.username,
            '이름': profile.name,
            '이메일': profile.user.email,
            '사번': profile.employee_id,
            '기수': profile.cohort.name if profile.cohort else '-',
            '소속 회사': profile.company.name if profile.company else '-',
            '공정': profile.process.name if profile.process else '-',
            '라인': profile.line if profile.line else '-',
            '담당 PL': profile.pl.name if profile.pl else '-',
            '상태': profile.get_status_display(),
        }

        # (B) 시험 점수 (1차, 2차, 3차)
        test_results = sorted(list(profile.user.testresult_set.all()), key=lambda x: x.completed_at)
        quiz_map = {}
        for res in test_results:
            if res.quiz_id not in quiz_map: quiz_map[res.quiz_id] = []
            quiz_map[res.quiz_id].append(res.score)
        
        for quiz in all_quizzes:
            attempts = quiz_map.get(quiz.id, [])
            row_data[f"[{quiz.title}] 1차"] = attempts[0] if len(attempts) > 0 else '-'
            row_data[f"[{quiz.title}] 2차"] = attempts[1] if len(attempts) > 1 else '-'
            row_data[f"[{quiz.title}] 3차"] = attempts[2] if len(attempts) > 2 else '-'

        # (C) 종합 평가 (FinalAssessment)
        fa = getattr(profile, 'final_assessment', None)
        row_data.update({
            '시험 평균': fa.exam_avg_score if fa else 0,
            '실습 점수': fa.practice_score if fa else 0,
            '노트 점수': fa.note_score if fa else 0,
            '태도 점수': fa.attitude_score if fa else 0,
            '최종 환산 점수': fa.final_score if fa else '-',
            '석차': fa.rank if fa else '-',
            '매니저 종합 의견': fa.manager_comment if fa else '-',
        })

        # (D) 체크리스트 평가 (ManagerEvaluation)
        last_eval = profile.managerevaluation_set.order_by('-created_at').first()
        checklist_str = ""
        if last_eval:
            items = last_eval.selected_items.all()
            checklist_str = "\n".join([f"[{'긍정' if item.is_positive else '부정'}] {item.description}" for item in items])
        row_data['체크리스트 평가'] = checklist_str

        # (E) 특이사항/경고 이력 (StudentLog)
        logs = profile.logs.all().order_by('created_at')
        log_str = ""
        for log in logs:
            log_str += f"[{log.created_at.strftime('%Y-%m-%d')}] {log.get_log_type_display()}: {log.reason}\n"
        row_data['특이사항/경고 이력'] = log_str

        # (F) 근태 요약 (DailySchedule)
        schedules = profile.dailyschedule_set.all()
        work_cnt = schedules.filter(work_type__deduction=0).count() # 정상출근
        leave_cnt = schedules.filter(work_type__deduction=1.0).count() # 연차
        half_cnt = schedules.filter(work_type__deduction=0.5).count() # 반차
        # 휴무 등 기타는 제외하고 주요 항목만 표시
        row_data['근태 요약'] = f"출근:{work_cnt} / 연차:{leave_cnt} / 반차:{half_cnt}"
        
        # 뱃지 정보
        badge_count = profile.badges.count()
        badge_list = ", ".join([b.name for b in profile.badges.all()])
        row_data['획득 뱃지 수'] = badge_count
        row_data['뱃지 목록'] = badge_list

        data_list.append(row_data)

    # 엑셀 파일 생성 및 이메일 발송
    try:
        df = pd.DataFrame(data_list)
        excel_file = BytesIO()
        with pd.ExcelWriter(excel_file, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='종합_데이터')
            
            # 스타일 적용 (줄바꿈 등)
            workbook = writer.book
            worksheet = writer.sheets['종합_데이터']
            format_wrap = workbook.add_format({'text_wrap': True, 'valign': 'top'})
            
            # 컬럼 너비 조정
            for idx, col in enumerate(df.columns):
                if col in ['특이사항/경고 이력', '체크리스트 평가', '매니저 종합 의견']:
                    worksheet.set_column(idx, idx, 50, format_wrap)
                elif col in ['사용자 ID', '이름', '이메일']:
                    worksheet.set_column(idx, idx, 20)
                else:
                    worksheet.set_column(idx, idx, 12)

        excel_file.seek(0)

        target_name = "전체"
        if target_process_id and target_process_id != 'ALL':
            try: target_name = Process.objects.get(pk=target_process_id).name
            except: pass
        elif my_process and not request.user.is_superuser:
            target_name = my_process.name

        subject = f"[보안] {request.user.profile.name}님 요청 데이터 ({target_name})"
        body = f"요청하신 데이터입니다.\n요청자: {request.user.profile.name}\n대상: {target_name}\n\n* 포함 내역: 기본정보, 성적, 평가, 특이사항, 근태"
        
        email = EmailMessage(
            subject, body, settings.EMAIL_HOST_USER, [request.user.email]
        )
        filename = f"{target_name}_Data_{timezone.now().strftime('%Y%m%d')}.xlsx"
        email.attach(filename, excel_file.read(), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        email.send()
        
        messages.success(request, f"✅ 상세 데이터가 포함된 엑셀 파일이 '{request.user.email}'로 발송되었습니다.")

    except Exception as e:
        print(f"Mail Error: {e}")
        messages.error(request, "메일 발송 중 오류가 발생했습니다. (로그 확인 필요)")

    return redirect('quiz:manager_dashboard')


# [수정 2] PL 대시보드 뷰 (슈퍼유저 권한 추가)
@login_required
def pl_dashboard(request):
    # (1) 권한 체크
    if not (request.user.is_staff and (request.user.profile.is_pl or request.user.is_superuser)):
        messages.error(request, "접근 권한이 없습니다.")
        return redirect('quiz:index')
    
    # (2) 기본 대상 설정
    if request.user.is_superuser:
        # 관리자는 전체 보기
        trainees = Profile.objects.select_related('user', 'cohort', 'process').all()
    else:
        try:
            pl_obj = PartLeader.objects.get(email=request.user.email)
            trainees = Profile.objects.filter(pl=pl_obj).select_related('user', 'cohort', 'process')
        except PartLeader.DoesNotExist:
            trainees = Profile.objects.none()

    # (3) 검색 및 필터링 적용
    search_query = request.GET.get('q', '')
    filter_cohort = request.GET.get('cohort', '')
    filter_process = request.GET.get('process', '')

    if search_query:
        trainees = trainees.filter(name__icontains=search_query)
    if filter_cohort:
        trainees = trainees.filter(cohort_id=filter_cohort)
    if filter_process:
        trainees = trainees.filter(process_id=filter_process)

    # (4) 통계 데이터 계산
    total_count = trainees.count()
    no_data = total_count == 0

    status_counts = {
        'attending': trainees.filter(status='attending').count(),
        'counseling': trainees.filter(status='counseling').count(),
        'dropout': trainees.filter(status='dropout').count(),
        'completed': trainees.filter(status='completed').count(),
    }

    assessed = trainees.filter(final_assessment__isnull=False)
    if assessed.exists():
        avg_final = assessed.aggregate(Avg('final_assessment__final_score'))['final_assessment__final_score__avg']
        radar_data = assessed.aggregate(
            avg_exam=Avg('final_assessment__exam_avg_score'),
            avg_prac=Avg('final_assessment__practice_score'),
            avg_note=Avg('final_assessment__note_score'),
            avg_atti=Avg('final_assessment__attitude_score')
        )
        top_trainees = assessed.order_by('-final_assessment__final_score')[:3]
    else:
        avg_final = 0
        radar_data = {'avg_exam':0, 'avg_prac':0, 'avg_note':0, 'avg_atti':0}
        top_trainees = []

    risk_trainees = trainees.filter(
        Q(status='counseling') | 
        (Q(final_assessment__final_score__lt=60) & Q(final_assessment__isnull=False))
    )

    # (5) 리스트 데이터 가공
    trainee_list = []
    for t in trainees:
        fa = getattr(t, 'final_assessment', None)
        trainee_list.append({
            'profile': t,
            'final_score': fa.final_score if fa else '-',
            'rank': fa.rank if fa else '-',
            'exam_avg': fa.exam_avg_score if fa else 0,
        })

    context = {
        'no_data': no_data,
        'total_count': total_count,
        'status_counts': list(status_counts.values()),
        'avg_final': round(avg_final, 1) if avg_final else 0,
        'radar_data': [
            round(radar_data['avg_exam'] or 0, 1),
            round(radar_data['avg_prac'] or 0, 1), 
            round(radar_data['avg_note'] or 0, 1), 
            round(radar_data['avg_atti'] or 0, 1)
        ],
        'top_trainees': top_trainees,
        'risk_trainees': risk_trainees,
        'trainee_list': trainee_list,
        
        'cohorts': Cohort.objects.all(),
        'processes': Process.objects.all(),
        'sel_q': search_query,
        'sel_cohort': int(filter_cohort) if filter_cohort else '',
        'sel_process': int(filter_process) if filter_process else '',
    }

    return render(request, 'quiz/pl_dashboard.html', context)

def get_pl_dashboard_data(pl_user):
    """
    담당 파트장(PL)의 교육생 명단을 가져와 가로형(피벗 테이블) 성적 데이터를 생성합니다.
    """
    try:
        part_leader_obj = PartLeader.objects.get(email=pl_user.email)
    except PartLeader.DoesNotExist:
        return []

    trainees = Profile.objects.filter(
        pl=part_leader_obj,
        user__is_superuser=False, # 슈퍼유저 제외
        is_manager=False,         # 매니저 제외
        is_pl=False               # PL 제외
    ).order_by('name').select_related('user', 'cohort', 'process')
    all_quizzes = Quiz.objects.all().order_by('title')
    
    data_list = []
    
    for trainee_profile in trainees:
        row = {
            'name': trainee_profile.name,
            'status': trainee_profile.get_status_display(),
            'cohort': trainee_profile.cohort.name if trainee_profile.cohort else '-',
        }
        
        results = trainee_profile.user.testresult_set.all().order_by('completed_at')
        
        for quiz in all_quizzes:
            quiz_attempts = results.filter(quiz=quiz)
            
            # 1차, 2차, 3차 점수 추출 (Horizontal Columns)
            score_1 = quiz_attempts[0].score if quiz_attempts.count() >= 1 else '-'
            score_2 = quiz_attempts[1].score if quiz_attempts.count() >= 2 else '-'
            score_3 = quiz_attempts[2].score if quiz_attempts.count() >= 3 else '-'
            
            row[f'{quiz.title}_1차'] = score_1
            row[f'{quiz.title}_2차'] = score_2
            row[f'{quiz.title}_3차'] = score_3
            
        data_list.append(row)
        
    return data_list

@login_required
def manager_dashboard(request):
    user = request.user
    if not (user.is_staff or (hasattr(user, 'profile') and (user.profile.is_manager or user.profile.is_pl))):
        messages.error(request, "접근 권한이 없습니다.")
        return redirect('quiz:index')

    signup_pending_count = User.objects.filter(is_active=False).count()
    
    if user.is_superuser:
        exam_pending_count = QuizAttempt.objects.filter(status='대기중').count()
    elif hasattr(user, 'profile') and user.profile.process:
        exam_pending_count = QuizAttempt.objects.filter(
            status='대기중', 
            user__profile__process=user.profile.process
        ).count()
    else:
        exam_pending_count = 0

    risk_qs = Profile.objects.filter(status='counseling')
    if not user.is_superuser and hasattr(user, 'profile') and user.profile.process:
        risk_qs = risk_qs.filter(process=user.profile.process)
    risk_count = risk_qs.count()

    context = {
        'signup_pending_count': signup_pending_count,
        'exam_pending_count': exam_pending_count,
        'risk_count': risk_count,
    }
    return render(request, 'quiz/manager/dashboard_main.html', context)


# 2. 교육생 목록 (드릴다운 진입점)
@login_required
def manager_trainee_list(request):
    if not request.user.is_staff: return redirect('quiz:index')

    # [신규 로직] 현재 날짜 기준 '진행 중인 기수' 찾기
    today = timezone.now().date()
    active_cohort = Cohort.objects.filter(start_date__lte=today, end_date__gte=today).first()
    
    # GET 파라미터가 없으면 '현재 기수'를 기본값으로 설정
    default_cohort = active_cohort.id if active_cohort else ''
    
    # 폼 초기값 설정 (request.GET이 비어있으면 default 사용)
    data = request.GET.copy()
    if 'cohort' not in data and default_cohort:
        data['cohort'] = default_cohort
    
    form = TraineeFilterForm(data)
    profiles = Profile.objects.select_related('user', 'cohort', 'process').exclude(user__is_superuser=True, is_manager=True).order_by('cohort__start_date', 'name')

    if form.is_valid():
        if form.cleaned_data['cohort']:
            profiles = profiles.filter(cohort=form.cleaned_data['cohort'])
        if form.cleaned_data['process']:
            profiles = profiles.filter(process=form.cleaned_data['process'])
        if form.cleaned_data['status']:
            profiles = profiles.filter(status=form.cleaned_data['status'])
        if form.cleaned_data['search']:
            q = form.cleaned_data['search']
            profiles = profiles.filter(Q(name__icontains=q) | Q(employee_id__icontains=q) | Q(user__username__icontains=q))

    # 매니저 권한: 본인 공정 우선 (필요시 강제)
    if not request.user.is_superuser and hasattr(request.user, 'profile') and request.user.profile.process:
        # profiles = profiles.filter(process=request.user.profile.process) 
        pass

    paginator = Paginator(profiles, 50)
    page_obj = paginator.get_page(request.GET.get('page'))
    pending_users = User.objects.filter(is_active=False).order_by('-date_joined')

    context = {
        'form': form,
        'profiles': page_obj,
        'pending_users': pending_users,
        'total_count': profiles.count(),
    }
    return render(request, 'quiz/manager/trainee_list.html', context)


# 3. 교육생 상세 (드릴다운 상세)
@login_required
def manager_trainee_detail(request, profile_id):
    if not request.user.is_staff: return redirect('quiz:index')
    
    profile = get_object_or_404(Profile, pk=profile_id)
    
    # 1. 시험 결과 (최신순)
    results = TestResult.objects.filter(user=profile.user).order_by('-completed_at')
    
    # 2. [수정됨] 면담 기록 (Interview -> StudentLog)
    # profile.interviews 가 아니라 profile.logs 를 가져와야 합니다.
    logs = profile.logs.all().order_by('-created_at')
    
    # 3. 획득 뱃지
    badges = profile.badges.all()

    context = {
        'profile': profile,
        'results': results,
        'logs': logs,  # interviews 대신 logs 전달
        'badges': badges,
    }
    return render(request, 'quiz/manager/trainee_detail.html', context)


# 4. 액션: 비번 초기화 (AJAX)
@login_required
@require_POST
def reset_password_bulk(request):
    if not request.user.is_staff:
        return JsonResponse({'status': 'error', 'message': '권한이 없습니다.'}, status=403)

    try:
        data = json.loads(request.body)
        user_ids = data.get('user_ids', [])
        
        users = User.objects.filter(id__in=user_ids)
        count = 0
        for user in users:
            user.set_password('1234')
            if hasattr(user, 'profile'):
                user.profile.must_change_password = True
                user.profile.save()
            user.save()
            count += 1
            
        return JsonResponse({'status': 'success', 'message': f'{count}명의 비밀번호가 1234로 초기화되었습니다.'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


# 5. 액션: 가입 승인 (AJAX)
@login_required
@require_POST
def approve_signup_bulk(request):
    if not request.user.is_staff:
        return JsonResponse({'status': 'error', 'message': '권한이 없습니다.'}, status=403)
        
    try:
        data = json.loads(request.body)
        user_ids = data.get('user_ids', [])
        action = data.get('action') 

        users = User.objects.filter(id__in=user_ids)
        count = 0
        
        if action == 'approve':
            for user in users:
                user.is_active = True
                user.save()
                count += 1
            msg = f'{count}명의 가입을 승인했습니다.'
        else:
            count = users.count()
            users.delete()
            msg = f'{count}명의 가입 요청을 거절(삭제)했습니다.'

        return JsonResponse({'status': 'success', 'message': msg})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


# 6. [누락되었던 함수] 액션: 계정 잠금 해제 (AJAX)
@login_required
@require_POST
def unlock_account(request, profile_id):
    if not request.user.is_staff:
        return JsonResponse({'status': 'error', 'message': '권한이 없습니다.'}, status=403)
    
    try:
        profile = get_object_or_404(Profile, pk=profile_id)
        # 상담 필요 상태이거나 퇴소 상태인 경우 -> 재직으로 복구
        if profile.status in ['counseling', 'dropout']:
            profile.status = 'attending'
            profile.save()
            return JsonResponse({'status': 'success', 'message': '계정 잠금이 해제되었습니다. (재직 상태로 변경)'})
        else:
            return JsonResponse({'status': 'info', 'message': '이미 정상(재직) 상태입니다.'})
            
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


# 7. 응시 요청 관리 페이지
@login_required
def manager_exam_requests(request):
    if not request.user.is_staff: return redirect('quiz:index')

    # 매니저의 경우 자기 공정 요청만 보기
    if not request.user.is_superuser and hasattr(request.user, 'profile') and request.user.profile.process:
        requests = QuizAttempt.objects.filter(
            status='대기중',
            user__profile__process=request.user.profile.process
        ).order_by('requested_at')
    else:
        requests = QuizAttempt.objects.filter(status='대기중').order_by('requested_at')

    return render(request, 'quiz/manager/exam_requests.html', {'requests': requests})

# --- PL 전용 대시보드 뷰 ---
# 1. PL 대시보드 (필터링 기능 강화)
@login_required
def pl_dashboard(request):
    # (1) 권한 체크
    if not (request.user.is_staff and (request.user.profile.is_pl or request.user.is_superuser)):
        messages.error(request, "접근 권한이 없습니다.")
        return redirect('quiz:index')
    
    # (2) 기본 대상 설정 (관리자 vs PL)
    if request.user.is_superuser:
        trainees = Profile.objects.select_related('user', 'cohort', 'process').all()
    else:
        try:
            pl_obj = PartLeader.objects.get(email=request.user.email)
            trainees = Profile.objects.filter(pl=pl_obj).select_related('user', 'cohort', 'process')
        except PartLeader.DoesNotExist:
            trainees = Profile.objects.none()

    # (3) 검색 및 필터링 적용
    search_query = request.GET.get('q', '')
    filter_cohort = request.GET.get('cohort', '')
    filter_process = request.GET.get('process', '')

    if search_query:
        trainees = trainees.filter(name__icontains=search_query) # 이름 검색
    if filter_cohort:
        trainees = trainees.filter(cohort_id=filter_cohort)      # 기수 필터
    if filter_process:
        trainees = trainees.filter(process_id=filter_process)    # 공정 필터

    # (4) 통계 데이터 계산 (필터링된 인원 기준)
    total_count = trainees.count()
    no_data = total_count == 0

    # 상태별 카운트
    status_counts = {
        'attending': trainees.filter(status='attending').count(),
        'counseling': trainees.filter(status='counseling').count(),
        'dropout': trainees.filter(status='dropout').count(),
        'completed': trainees.filter(status='completed').count(),
    }

    # 평균 및 Top 3
    assessed = trainees.filter(final_assessment__isnull=False)
    if assessed.exists():
        avg_final = assessed.aggregate(Avg('final_assessment__final_score'))['final_assessment__final_score__avg']
        radar_data = assessed.aggregate(
            avg_exam=Avg('final_assessment__exam_avg_score'),
            avg_prac=Avg('final_assessment__practice_score'),
            avg_note=Avg('final_assessment__note_score'),
            avg_atti=Avg('final_assessment__attitude_score')
        )
        top_trainees = assessed.order_by('-final_assessment__final_score')[:3]
    else:
        avg_final = 0
        radar_data = {'avg_exam':0, 'avg_prac':0, 'avg_note':0, 'avg_atti':0}
        top_trainees = []

    risk_trainees = trainees.filter(
        Q(status='counseling') | 
        (Q(final_assessment__final_score__lt=60) & Q(final_assessment__isnull=False))
    )

    # (5) 리스트 데이터 가공
    trainee_list = []
    for t in trainees:
        fa = getattr(t, 'final_assessment', None)
        trainee_list.append({
            'profile': t,
            'final_score': fa.final_score if fa else '-',
            'rank': fa.rank if fa else '-',
            'exam_avg': fa.exam_avg_score if fa else 0,
        })

    context = {
        'no_data': no_data,
        'total_count': total_count,
        'status_counts': list(status_counts.values()),
        'avg_final': round(avg_final, 1) if avg_final else 0,
        'radar_data': [
            round(radar_data['avg_exam'] or 0, 1),
            round(radar_data['avg_prac'] or 0, 1), 
            round(radar_data['avg_note'] or 0, 1), 
            round(radar_data['avg_atti'] or 0, 1)
        ],
        'top_trainees': top_trainees,
        'risk_trainees': risk_trainees,
        'trainee_list': trainee_list,
        
        # 필터링용 목록 (드롭다운)
        'cohorts': Cohort.objects.all(),
        'processes': Process.objects.all(),
        'sel_q': search_query,
        'sel_cohort': int(filter_cohort) if filter_cohort else '',
        'sel_process': int(filter_process) if filter_process else '',
    }

    return render(request, 'quiz/pl_dashboard.html', context)


# 2. [수정됨] 교육생 상세 점수 가져오기 (AJAX 모달용 - 태그/평가 포함)
@login_required
def pl_trainee_detail(request, profile_id):
    # 권한 체크 (PL 본인 담당 또는 관리자 또는 같은 공정 매니저)
    profile = get_object_or_404(Profile, pk=profile_id)
    
    is_authorized = False
    if request.user.is_superuser:
        is_authorized = True
    elif hasattr(request.user, 'profile'):
        # 같은 공정 매니저 허용
        if request.user.profile.is_manager and request.user.profile.process == profile.process:
            is_authorized = True
        # 담당 PL 허용
        elif request.user.profile.is_pl:
            try:
                pl_obj = PartLeader.objects.get(email=request.user.email)
                if profile.pl == pl_obj: is_authorized = True
            except: pass

    if not is_authorized:
        return JsonResponse({'error': '권한이 없습니다.'}, status=403)

    # 1. 시험 점수 데이터
    all_quizzes = Quiz.objects.all().order_by('title')
    results = profile.user.testresult_set.all().order_by('completed_at')
    
    score_data = []
    for quiz in all_quizzes:
        attempts = results.filter(quiz=quiz)
        # 1~3차 점수 추출
        scores = [a.score for a in attempts]
        while len(scores) < 3:
            scores.append('-')
        
        score_data.append({
            'quiz_title': quiz.title,
            'scores': scores[:3]
        })

    # 2. [신규] 태그 기반 강/약점 분석
    tag_stats = calculate_tag_stats(profile.user)

    # 3. [신규] 매니저 평가 (체크리스트 & 코멘트)
    eval_data = {}
    manager_eval = ManagerEvaluation.objects.filter(trainee_profile=profile).last()
    
    if manager_eval:
        eval_data['comment'] = manager_eval.overall_comment
        # 체크된 항목들 리스트로 변환
        eval_data['checklist'] = [
            {'category': item.category.name, 'desc': item.description, 'is_positive': item.is_positive}
            for item in manager_eval.selected_items.all().order_by('category__order')
        ]
        
        # 종합 점수 (FinalAssessment)
        fa = getattr(profile, 'final_assessment', None)
        if fa:
            eval_data['scores'] = {
                'exam': fa.exam_avg_score,
                'practice': fa.practice_score,
                'note': fa.note_score,
                'attitude': fa.attitude_score,
                'final': fa.final_score,
                'rank': fa.rank
            }

    return JsonResponse({
        'name': profile.name,
        'status': profile.get_status_display(),
        'exam_data': score_data,
        'tag_stats': tag_stats,   # 추가됨
        'evaluation': eval_data   # 추가됨
    })

# --- 1. 최종 점수 및 랭킹 계산 유틸리티 ---

def calculate_cohort_ranking(cohort_id):
    """특정 기수 내 최종 점수 기준으로 등수를 매기는 함수"""
    
    # 1. 기수 내 모든 FinalAssessment 가져오기 (최종 점수 기준으로 정렬)
    assessments = FinalAssessment.objects.filter(profile__cohort__id=cohort_id).order_by('-final_score')
    
    # 2. 랭킹 계산 (DenseRank 사용: 동점자에게 같은 등수를 부여합니다)
    ranked_assessments = assessments.annotate(
        rank=Window(
            expression=DenseRank(),
            order_by=[F('final_score').desc()]
        )
    )
    
    # 3. DB에 순위 반영
    for assessment in ranked_assessments:
        # 이미 랭킹이 계산된 값이 annotate 되어 있으므로 그대로 저장
        assessment.rank = assessment.rank
        assessment.save(update_fields=['rank'])


# --- 2. 랭킹 일괄 업데이트 (모든 기수) ---

def update_all_cohort_rankings():
    """DB에 있는 모든 기수의 랭킹을 일괄 계산하여 반영합니다."""
    cohort_ids = Cohort.objects.all().values_list('id', flat=True)
    for cohort_id in cohort_ids:
        calculate_cohort_ranking(cohort_id)

@login_required
def request_process_access(request):
    if request.method == 'POST':
        target_id = request.POST.get('target_process_id')
        
        # target_id가 'ALL'이면 전체 요청 (target_process=None)
        target_process = None
        target_name = "🌍 전체 공정"
        
        if target_id and target_id != 'ALL':
            target_process = get_object_or_404(Process, pk=target_id)
            target_name = target_process.name

        # 중복 요청 확인
        existing = ProcessAccessRequest.objects.filter(
            requester=request.user, 
            target_process=target_process, # None이면 전체 검색
            status__in=['pending', 'approved']
        ).first()
        
        if existing:
            msg_status = "승인되었습니다" if existing.status == 'approved' else "대기 중입니다"
            messages.warning(request, f"이미 '{target_name}' 권한이 {msg_status}.")
        else:
            ProcessAccessRequest.objects.create(
                requester=request.user,
                target_process=target_process # None이면 전체
            )
            messages.success(request, f"'{target_name}' 열람 권한을 요청했습니다.")

    return redirect('quiz:dashboard')

# 2. 요청 관리 페이지 (최고 관리자 전용)
@login_required
def manage_access_requests(request):
    if not request.user.is_superuser:
        messages.error(request, "접근 권한이 없습니다.")
        return redirect('quiz:dashboard')
        
    pending_requests = ProcessAccessRequest.objects.filter(status='pending').order_by('-created_at')
    
    return render(request, 'quiz/manage_access_requests.html', {'requests': pending_requests})

# 3. 승인/거절 처리 (최고 관리자 전용)
@login_required
def approve_access_request(request, request_id, action):
    if not request.user.is_superuser:
        return redirect('quiz:dashboard')
        
    access_req = get_object_or_404(ProcessAccessRequest, pk=request_id)
    
    if action == 'approve':
        access_req.status = 'approved'
        access_req.save()
        messages.success(request, f"{access_req.requester.profile.name}님의 요청을 승인했습니다.")
    elif action == 'reject':
        access_req.status = 'rejected'
        access_req.save()
        messages.warning(request, "요청을 거절했습니다.")
        
    return redirect('quiz:manage_access_requests')

@login_required
def manage_interviews(request, profile_id):
    """
    [구버전 호환용]
    예전 면담 페이지 URL로 접속 시, 새로운 '특이사항/경고 관리' 페이지로 이동시킵니다.
    """
    return redirect('quiz:manage_student_logs', profile_id=profile_id)

@login_required
def manager_quiz_list(request):
    """매니저용 시험 목록 관리"""
    if not request.user.is_staff: return redirect('quiz:index')
    
    # 관리자는 전체, 매니저는 (공통 + 자기공정)
    if request.user.is_superuser:
        quizzes = Quiz.objects.all().order_by('-id')
    elif hasattr(request.user, 'profile') and request.user.profile.process:
        my_process = request.user.profile.process
        quizzes = Quiz.objects.filter(
            Q(category=Quiz.Category.COMMON) | Q(associated_process=my_process)
        ).distinct().order_by('-id')
    else:
        # 공정 없는 매니저는 공통만
        quizzes = Quiz.objects.filter(category=Quiz.Category.COMMON).order_by('-id')

    return render(request, 'quiz/manager/quiz_list.html', {'quizzes': quizzes})

@login_required
def quiz_create(request):
    if not request.user.is_staff: return redirect('quiz:index')
    
    if request.method == 'POST':
        form = QuizForm(request.POST)
        if form.is_valid():
            quiz = form.save()
            messages.success(request, f"시험 '{quiz.title}'이(가) 생성되었습니다.")
            return redirect('quiz:manager_quiz_list')
    else:
        form = QuizForm()
    
    return render(request, 'quiz/manager/quiz_form.html', {'form': form, 'title': '새 시험 만들기'})

@login_required
def quiz_update(request, quiz_id):
    if not request.user.is_staff: return redirect('quiz:index')
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    
    if request.method == 'POST':
        form = QuizForm(request.POST, instance=quiz)
        if form.is_valid():
            form.save()
            messages.success(request, "시험 정보가 수정되었습니다.")
            return redirect('quiz:manager_quiz_list')
    else:
        form = QuizForm(instance=quiz)
    
    return render(request, 'quiz/manager/quiz_form.html', {'form': form, 'title': '시험 수정'})

@login_required
def quiz_delete(request, quiz_id):
    if not request.user.is_staff: return redirect('quiz:index')
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    
    if request.method == 'POST':
        quiz.delete()
        messages.success(request, "시험이 삭제되었습니다.")
    
    return redirect('quiz:manager_quiz_list')

# --- 문제(Question) 관리 뷰 ---

@login_required
def question_list(request, quiz_id):
    if not request.user.is_staff: return redirect('quiz:index')
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    questions = quiz.question_set.all()
    return render(request, 'quiz/manager/question_list.html', {'quiz': quiz, 'questions': questions})

@login_required
def question_create(request, quiz_id):
    if not request.user.is_staff: return redirect('quiz:index')
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    
    # [핵심] 보기(Choice) 입력 폼셋 정의
    # extra=4 : 새 문제 작성 시 빈 보기 칸 4개를 미리 보여줌
    ChoiceFormSet = inlineformset_factory(Question, Choice, fields=('choice_text', 'is_correct'), extra=4, can_delete=False)

    if request.method == 'POST':
        form = QuestionForm(request.POST, request.FILES)
        formset = ChoiceFormSet(request.POST)
        
        if form.is_valid() and formset.is_valid():
            question = form.save(commit=False)
            question.quiz = quiz
            question.save()
            
            # [중요] 폼셋에 방금 만든 문제(instance)를 연결하고 저장
            choices = formset.save(commit=False)
            for choice in choices:
                # 내용이 있는 보기만 저장 (빈칸은 무시)
                if choice.choice_text.strip():
                    choice.question = question
                    choice.save()
            
            form.save_m2m() # 태그 저장
            messages.success(request, "문제와 보기가 성공적으로 등록되었습니다.")
            return redirect('quiz:question_list', quiz_id=quiz.id)
    else:
        form = QuestionForm()
        # GET 요청 시 빈 폼셋 생성 (보기 1~4번 입력칸)
        formset = ChoiceFormSet()
    
    return render(request, 'quiz/manager/question_form.html', {
        'form': form, 
        'formset': formset, # 템플릿으로 폼셋 전달
        'quiz': quiz, 
        'title': '새 문제 추가'
    })

@login_required
def question_update(request, question_id):
    if not request.user.is_staff: return redirect('quiz:index')
    question = get_object_or_404(Question, pk=question_id)
    
    # [핵심] Question과 연결된 Choice들을 수정하기 위한 폼셋 생성
    # extra=0: 빈 줄 추가 안 함 (기존 보기만 수정)
    # can_delete=False: 삭제 불가 (보통 4지선다 유지하므로)
    ChoiceFormSet = inlineformset_factory(Question, Choice, fields=('choice_text', 'is_correct'), extra=0, can_delete=False)

    if request.method == 'POST':
        form = QuestionForm(request.POST, request.FILES, instance=question)
        formset = ChoiceFormSet(request.POST, instance=question)
        
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save() # 보기(Choice) 수정 사항 저장
            messages.success(request, "문제와 보기가 성공적으로 수정되었습니다.")
            return redirect('quiz:question_list', quiz_id=question.quiz.id)
    else:
        form = QuestionForm(instance=question)
        formset = ChoiceFormSet(instance=question)
    
    return render(request, 'quiz/manager/question_form.html', {
        'form': form, 
        'formset': formset, # 폼셋 전달
        'quiz': question.quiz, 
        'title': '문제 수정'
    })

@login_required
def question_delete(request, question_id):
    if not request.user.is_staff: return redirect('quiz:index')
    question = get_object_or_404(Question, pk=question_id)
    quiz_id = question.quiz.id
    if request.method == 'POST':
        question.delete()
        messages.success(request, "문제가 삭제되었습니다.")
    return redirect('quiz:question_list', quiz_id=quiz_id)


@login_required
def evaluate_trainee(request, profile_id):
    # 1. 대상자 조회 및 권한 체크
    trainee = get_object_or_404(Profile, pk=profile_id)
    
    # [보안] 담당 매니저(교수) 또는 관리자만 평가 가능
    if not is_process_manager(request.user, trainee):
        messages.error(request, "🚫 담당 공정의 매니저만 평가서를 작성할 수 있습니다.")
        return redirect('quiz:dashboard')

    # 2. 기존 평가 데이터 가져오기 (수정 모드)
    existing_evaluation = ManagerEvaluation.objects.filter(trainee_profile=trainee).first()
    final_assessment, _ = FinalAssessment.objects.get_or_create(profile=trainee)

    if request.method == 'POST':
        form = EvaluationForm(request.POST, instance=existing_evaluation)
        if form.is_valid():
            # (1) 정성 평가 (체크리스트 + 코멘트) 저장
            evaluation = form.save(commit=False)
            evaluation.manager = request.user
            evaluation.trainee_profile = trainee
            evaluation.save()
            form.save_m2m()
            
            # (2) 정량 평가 (점수) 저장 - FinalAssessment 모델 업데이트
            try:
                final_assessment.practice_score = float(request.POST.get('practice_score', 0))
                final_assessment.note_score = float(request.POST.get('note_score', 0))
                final_assessment.attitude_score = float(request.POST.get('attitude_score', 0))
                
                # 최종 점수 재계산 (Signal이 처리하거나 직접 호출)
                final_assessment.calculate_final_score() 
                final_assessment.save()
                
                messages.success(request, f"✅ {trainee.name} 님의 최종 평가가 저장되었습니다.")
                return redirect('quiz:manager_trainee_detail', profile_id=trainee.id)
            except ValueError:
                messages.error(request, "점수는 숫자만 입력 가능합니다.")

    else:
        form = EvaluationForm(instance=existing_evaluation)

    # 3. [종합 데이터 로드] 평가를 위한 참고 자료
    # (A) 성적 현황
    test_results = TestResult.objects.filter(user=trainee.user)
    avg_score = test_results.aggregate(Avg('score'))['score__avg'] or 0
    fail_count = test_results.filter(is_pass=False).count()
    
    # (B) 근태 현황 (DailySchedule 집계)
    attendance_stats = DailySchedule.objects.filter(profile=trainee).values('work_type__name').annotate(count=Count('id'))
    # 예: [{'work_type__name': '지각', 'count': 2}, ...]
    
    # (C) 특이사항/상벌점 로그
    logs = StudentLog.objects.filter(profile=trainee).order_by('-created_at')

    # (D) 체크리스트 항목
    categories = EvaluationCategory.objects.prefetch_related('evaluationitem_set').order_by('order')

    context = {
        'trainee': trainee,
        'form': form,
        'categories': categories,
        'final_assessment': final_assessment, # 점수 입력용
        
        # 참고 데이터
        'avg_score': round(avg_score, 1),
        'fail_count': fail_count,
        'attendance_stats': attendance_stats,
        'logs': logs,
    }
    return render(request, 'quiz/evaluate_trainee.html', context)

@login_required
def certificate_view(request):
    # 수료 상태가 아니면 튕겨냄
    if request.user.profile.status != 'completed':
        messages.error(request, "수료한 교육생만 수료증을 발급받을 수 있습니다.")
        return redirect('quiz:my_page')
    
    return render(request, 'quiz/certificate.html', {'profile': request.user.profile})

@login_required
def pl_report_view(request):
    # 1. 권한 및 PL 정보 확인
    if not (request.user.is_staff and (request.user.profile.is_pl or request.user.is_superuser)):
        messages.error(request, "접근 권한이 없습니다.")
        return redirect('quiz:index')

    # 2. 대상자 필터링 (대시보드와 동일한 로직 적용)
    if request.user.is_superuser:
        trainees = Profile.objects.select_related('user', 'cohort', 'process').all()
    else:
        try:
            pl_obj = PartLeader.objects.get(email=request.user.email)
            trainees = Profile.objects.filter(pl=pl_obj).select_related('user', 'cohort', 'process')
        except PartLeader.DoesNotExist:
            trainees = Profile.objects.none()

    # 3. 검색 조건 적용 (대시보드에서 선택한 조건 그대로 가져옴)
    search_query = request.GET.get('q', '')
    filter_cohort = request.GET.get('cohort', '')
    filter_process = request.GET.get('process', '')

    if search_query:
        trainees = trainees.filter(name__icontains=search_query)
    if filter_cohort:
        trainees = trainees.filter(cohort_id=filter_cohort)
    if filter_process:
        trainees = trainees.filter(process_id=filter_process)

    # 4. [핵심] 리포트용 상세 데이터 구성 (점수 + 의견)
    all_quizzes = Quiz.objects.all().order_by('title')
    report_data = []

    for t in trainees:
        # (1) 시험 점수 상세 내역
        results = t.user.testresult_set.all().order_by('completed_at')
        scores_list = []
        
        for quiz in all_quizzes:
            attempts = results.filter(quiz=quiz)
            # 1, 2, 3차 점수 추출
            s1 = attempts[0].score if attempts.count() >= 1 else '-'
            s2 = attempts[1].score if attempts.count() >= 2 else '-'
            s3 = attempts[2].score if attempts.count() >= 3 else '-'
            scores_list.append({'title': quiz.title, 's1': s1, 's2': s2, 's3': s3})

        # (2) 종합 평가 및 매니저 의견
        fa = getattr(t, 'final_assessment', None)
        final_info = {
            'final_score': fa.final_score if fa else '-',
            'rank': fa.rank if fa else '-',
            'comment': fa.manager_comment if fa and fa.manager_comment else "작성된 평가 의견이 없습니다."
        }

        report_data.append({
            'profile': t,
            'scores': scores_list,
            'assessment': final_info
        })

    context = {
        'report_data': report_data,
        'today': timezone.now().date(),
    }
    return render(request, 'quiz/pl_report_print.html', context)

@login_required
def manage_student_logs(request, profile_id):
    # 1. 권한 체크
    if not request.user.is_staff:
        return redirect('quiz:index')

    profile = get_object_or_404(Profile, pk=profile_id)
    logs = profile.logs.all()

    if request.method == 'POST':
        form = StudentLogForm(request.POST)
        if form.is_valid():
            log = form.save(commit=False)
            log.profile = profile
            log.recorder = request.user
            
            # --- [핵심 비즈니스 로직] ---
            
            # A. 일반 경고 등록
            if log.log_type == 'warning':
                profile.warning_count += 1
                log.save() # 경고 로그 저장
                
                # 누적 2회 -> 1차 경고장 자동 발부 (매니저 면담 필요)
                if profile.warning_count == 2:
                    StudentLog.objects.create(
                        profile=profile, recorder=request.user,
                        log_type='warning_letter',
                        reason="[시스템 자동] 일반 경고 2회 누적으로 인한 1차 경고장 발부"
                    )
                    profile.status = 'counseling' # 잠금
                    messages.warning(request, "⚠️ 경고 2회 누적! 1차 경고장이 발부되고 계정이 잠겼습니다.")

                # 누적 3회 -> 2차 경고장 자동 발부 (PL 면담 필요)
                elif profile.warning_count == 3:
                    StudentLog.objects.create(
                        profile=profile, recorder=request.user,
                        log_type='warning_letter',
                        reason="[시스템 자동] 일반 경고 3회 누적으로 인한 2차 경고장 발부"
                    )
                    profile.status = 'counseling'
                    messages.error(request, "🚫 경고 3회 누적! 2차 경고장이 발부되었습니다. (PL 면담 필수)")

                # 누적 4회 -> 퇴소
                elif profile.warning_count >= 4:
                    profile.status = 'dropout'
                    messages.error(request, "⛔ 경고 4회 누적! 퇴소 처리되었습니다.")
                
                else:
                    profile.status = 'caution' # 1회는 주의 상태
                    messages.info(request, "일반 경고가 등록되었습니다.")
            
            # B. 경고장 즉시 발부 (중대 과실)
            elif log.log_type == 'warning_letter':
                # 즉시 발부 시 경고 카운트를 강제로 2회(또는 상황에 맞춰)로 조정하거나 유지
                # 여기서는 중대 과실이므로 바로 잠금 처리
                profile.status = 'counseling'
                log.save()
                messages.warning(request, "⛔ 경고장이 즉시 발부되었습니다. 계정이 잠깁니다.")

            # C. 면담 및 조치 (잠금 해제)
            elif log.log_type == 'counseling':
                # 화면에서 '조치 완료(잠금해제)' 체크박스를 받음 (폼에는 없으므로 request.POST 확인)
                is_resolve = request.POST.get('resolve_lock') == 'on'
                log.is_resolved = is_resolve
                log.save()

                if is_resolve:
                    if profile.warning_count >= 4: # 4회 이상이면 퇴소 유지
                        profile.status = 'dropout'
                    else:
                        profile.status = 'attending' # 정상 복귀
                        messages.success(request, "✅ 면담 후 조치가 완료되어 계정이 정상화되었습니다.")
                else:
                    messages.info(request, "면담 내용이 기록되었습니다.")

            else:
                log.save()
                messages.success(request, "기록이 저장되었습니다.")

            profile.save()
            return redirect('quiz:manage_student_logs', profile_id=profile.id)

    else:
        form = StudentLogForm()

    context = {
        'profile': profile,
        'logs': logs,
        'form': form,
    }
    return render(request, 'quiz/manager/manage_student_logs.html', context)


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