import json
import random
import pandas as pd
import os
import urllib.parse
from openpyxl import Workbook  # 👈 [추가 2] 엑셀 생성을 위해 필요 (만약 pandas만 쓴다면 생략 가능)
from collections import defaultdict
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
from django.contrib.auth import get_user_model
from django.views.decorators.cache import cache_control
from django.core.mail import send_mail
from django.contrib.admin.views.decorators import staff_member_required
from django.views.decorators.http import require_POST
from django.db import transaction

from django.forms import inlineformset_factory
# [핵심] 데이터 분석 및 집계를 위한 필수 모듈 (누락된 부분 추가됨)
from django.db.models import Avg, Count, Q, Max,Min, F, Case, When, Value, CharField, Window
from attendance.models import DailySchedule, ScheduleRequest
from django.db.models.functions import DenseRank, Coalesce
from .utils import calculate_tag_stats
from django.conf import settings
# accounts 앱의 모델들
from accounts.models import (
    Profile, Badge, EvaluationRecord, EvaluationCategory, 
    ManagerEvaluation, Cohort, Company, Process, ProcessAccessRequest, FinalAssessment, PartLeader,Profile, 
)

# quiz 앱의 모델들
from .models import (
    Quiz, Question, Choice, TestResult, UserAnswer, 
    QuizAttempt, ExamSheet, Tag, StudentLog, Notification, QuizResult, StudentAnswer
)

# 폼
from .forms import EvaluationForm, TraineeFilterForm, QuizForm, QuestionForm, StudentLogForm, ChoiceForm

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
    """
    마이페이지 (홈)
    - 매니저 강제 리다이렉트 제거됨 (누구나 접근 가능)
    - 시험 불합격 시 면담 요청 상태(예정/완료) 체크 로직 포함
    - [수정 완료] 템플릿 경로를 실제 파일 위치인 'quiz/my_page.html'로 변경
    """
    user = request.user
    
    # 1. 프로필 가져오기 (없으면 생성)
    profile, created = Profile.objects.get_or_create(user=user)

    # -------------------------------------------------------
    # [1] 진행 중인 시험 (결재 대기/승인됨)
    # -------------------------------------------------------
    pending_attempts = QuizAttempt.objects.filter(
        user=user, 
        status__in=['대기중', '승인됨']
    )

    # -------------------------------------------------------
    # [2] 시험 결과 + 면담 상태 데이터 가공 (핵심 로직)
    # -------------------------------------------------------
    # 최근 5개 결과 조회
    raw_results = TestResult.objects.filter(user=user).select_related('quiz').order_by('-completed_at')[:5]
    enhanced_results = []

    for result in raw_results:
        counseling_status = None
        
        # 불합격(is_pass=False)인 경우에만 면담 로직 체크
        if not result.is_pass:
            # 이미 해당 시험 제목으로 면담/특이사항 기록이 있는지 확인
            # (로그 내용에 시험 제목이 포함되어 있는지로 단순 판단)
            exists_log = StudentLog.objects.filter(
                profile=profile,
                log_type='counseling',
                reason__contains=result.quiz.title 
            ).exists()

            if exists_log:
                counseling_status = '완료' # 이미 상담함
            else:
                counseling_status = '예정' # 상담 버튼이 떠야 함 ('면담 요청' 필요)
        
        # 템플릿에서 사용할 데이터 구조 만들기
        enhanced_results.append({
            'result': result,
            'counseling_status': counseling_status
        })

    # -------------------------------------------------------
    # [3] 배지 & 최근 피드백 (평가 로그)
    # -------------------------------------------------------
    latest_badges = profile.badges.all().order_by('-id')[:3]
    
    latest_evaluations = StudentLog.objects.filter(
        profile=profile
    ).order_by('-created_at')[:3]
    
    # -------------------------------------------------------
    # [4] 통계 데이터 (옵션: 필요 시 사용)
    # -------------------------------------------------------
    # 전체 결과 재조회 (통계용)
    all_results = TestResult.objects.filter(user=user)
    total_tests = all_results.count()
    pass_count = all_results.filter(is_pass=True).count()
    
    avg_score = 0
    if total_tests > 0:
        total_score_sum = sum(r.score for r in all_results)
        avg_score = round(total_score_sum / total_tests, 1)

    context = {
        'profile': profile,
        'pending_attempts': pending_attempts,
        'enhanced_results': enhanced_results,   # [핵심] 상태 포함 결과 리스트
        'latest_badges': latest_badges,
        'latest_evaluations': latest_evaluations,
        'stats': {
            'total': total_tests,
            'passed': pass_count,
            'avg_score': avg_score,
        }
    }
    
    # [수정됨] 실제 파일이 존재하는 경로('quiz/my_page.html')로 변경했습니다.
    return render(request, 'quiz/my_page.html', context)


# [신규] 학생이 모달에서 면담 요청/사유를 작성하면 저장하는 함수
@login_required
@require_POST
def student_create_counseling_log(request):
    """
    교육생 면담/상담 요청 함수
    - 시험 성적 문의 -> 매니저의 '교육생 상세 정보(성적표)' 페이지로 이동
    - 기타/경고 문의 -> 매니저의 '로그 관리(특이사항)' 페이지로 이동
    """
    User = get_user_model() 

    try:
        # 1. 데이터 수신
        quiz_title = request.POST.get('quiz_title')
        score = request.POST.get('score')
        ref_log_type = request.POST.get('ref_log_type') 
        user_reason = request.POST.get('reason', '') 

        final_reason = ""
        noti_summary = ""
        target_url = "" # [핵심] 알림 클릭 시 이동할 URL 변수

        # [Case 1] 시험 불합격 원클릭 요청
        if quiz_title:
            final_reason = f"[면담 요청] '{quiz_title}' 시험 불합격 ({score}점)\n- 재시험 및 학습 상담 요청"
            noti_summary = f"'{quiz_title}' 불합격 면담 요청"
            # 시험 관련이므로 '성적 상세 페이지'로 이동
            target_url = reverse('quiz:manager_trainee_detail', args=[request.user.profile.id])
        
        # [Case 2] 특정 기록(경고 등) 상담 요청
        elif ref_log_type:
            final_reason = f"[상담 요청] 관련 기록: {ref_log_type}\n\n[내용]\n{user_reason}"
            noti_summary = f"특이사항({ref_log_type}) 관련 상담"
            # 기록 관련이므로 '로그 관리 페이지'로 이동
            target_url = reverse('quiz:manage_student_logs', args=[request.user.profile.id])
            
        # [Case 3] 일반 직접 작성
        elif user_reason:
            final_reason = user_reason
            # 내용이 길면 말줄임표 처리
            short_reason = (user_reason[:12] + '...') if len(user_reason) > 12 else user_reason
            noti_summary = f"면담 요청: {short_reason}"
            # 일반 상담이므로 '로그 관리 페이지'로 이동
            target_url = reverse('quiz:manage_student_logs', args=[request.user.profile.id])
            
        else:
            messages.error(request, "요청 내용이 없습니다.")
            return redirect('quiz:my_page')

        # 2. DB에 로그(StudentLog) 저장
        StudentLog.objects.create(
            profile=request.user.profile,
            created_by=request.user, 
            log_type='counseling',
            reason=final_reason,
            is_resolved=False 
        )
        
        # 3. 관리자 알림 발송
        managers = User.objects.filter(is_staff=True)
        
        for manager in managers:
            Notification.objects.create(
                recipient=manager,       
                sender=request.user,     
                message=f"📢 [{request.user.profile.name}] {noti_summary}",        
                notification_type='counseling', 
                related_url=target_url   # [핵심] 위에서 결정된 URL 저장
            )
        
        messages.success(request, "면담 요청이 전송되었습니다.")
        
    except Exception as e:
        messages.error(request, f"오류 발생: {e}")
    
    return redirect('quiz:my_page')

@login_required
def index(request):
    """
    대시보드 메인 페이지 (교육생 센터 홈)
    - [수정 완료] 매니저가 접속해도 강제로 튕겨내지 않도록 리다이렉트 로직 삭제
    """
    user = request.user

    # =======================================================
    # [삭제됨] 아래 코드가 매니저를 튕겨내는 원인이었습니다.
    # if user.is_superuser or (hasattr(user, 'profile') and user.profile.is_manager):
    #     return redirect('quiz:manager_dashboard')
    # =======================================================
    
    user_groups = user.groups.all()
    
    # 사용자 프로필 및 공정 정보 가져오기
    user_process = None
    if hasattr(user, 'profile') and user.profile.process:
        user_process = user.profile.process

    # -------------------------------------------------------
    # [1] 공통 과목 (Common)
    # -------------------------------------------------------
    all_common_quizzes = Quiz.objects.filter(
        category=Quiz.Category.COMMON
    ).distinct()

    # -------------------------------------------------------
    # [2] 권한 쿼리
    # -------------------------------------------------------
    permission_query = Q(allowed_groups__in=user_groups) | Q(allowed_users=user)

    # -------------------------------------------------------
    # [3] '나의 공정' 퀴즈 목록
    # -------------------------------------------------------
    my_process_condition = Q(related_process=user_process) | permission_query
    
    if user_process is None:
        my_process_condition = permission_query

    my_process_quizzes_list = Quiz.objects.filter(
        Q(category=Quiz.Category.PROCESS) & 
        (my_process_condition)
    ).distinct()

    # -------------------------------------------------------
    # [4] '기타 공정' 퀴즈 목록
    # -------------------------------------------------------
    other_process_quizzes_list = Quiz.objects.filter(
        category=Quiz.Category.PROCESS
    ).exclude(
        id__in=my_process_quizzes_list.values('id')
    ).distinct()

    # -------------------------------------------------------
    # [5] 합격 여부 카운팅
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
    # [6] 상태 처리 헬퍼 함수
    # -------------------------------------------------------
    def process_quiz_list(quiz_list):
        for quiz in quiz_list:
            quiz.user_status = None
            quiz.action_id = None
            quiz.is_pass = False 
            
            # 1. 최근 결과
            latest_result = TestResult.objects.filter(user=user, quiz=quiz).order_by('-completed_at').first()
            
            # 2. 요청 상태
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

            # 3. 그룹 상태
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
            
            # 4. 완료됨
            if latest_result:
                quiz.user_status = '완료됨'
                quiz.action_id = latest_result.id
                quiz.is_pass = latest_result.is_pass
                continue
            
            # 5. 기본
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
        'profile': getattr(user, 'profile', None),
    }
    return render(request, 'quiz/index.html', context)

@login_required
def request_quiz(request, quiz_id):
    quiz = get_object_or_404(Quiz, pk=quiz_id)

    # [수정] 대기중이거나 승인된 요청이 있는지 확인
    existing_attempt = QuizAttempt.objects.filter(
        user=request.user, 
        quiz=quiz, 
        status__in=['대기중', '승인됨']
    ).first()

    if existing_attempt:
        # [해결] 이미 승인된 상태라면 '요청' 에러가 아니라 '시험 시작'을 유도해야 꼬이지 않음
        if existing_attempt.status == '승인됨':
            messages.info(request, f"이미 승인된 '{quiz.title}' 시험이 있습니다. 바로 응시해주세요.")
        else:
            messages.warning(request, f"이미 '{quiz.title}' 시험 요청이 대기 중입니다.")
    else:
        # 새로운 요청 생성
        QuizAttempt.objects.create(
            user=request.user, 
            quiz=quiz, 
            assignment_type=QuizAttempt.AssignmentType.INDIVIDUAL,
            status='대기중' # 기본값
        )
        messages.success(request, f"'{quiz.title}' 시험 응시를 요청했습니다. 관리자의 승인을 기다려 주세요.")
    
    return redirect('quiz:index')

@login_required
@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def take_quiz(request, quiz_id):
    quiz = get_object_or_404(Quiz, pk=quiz_id)

    # 1. 세션/DB에서 시도(Attempt) 정보 가져오기
    attempt_id = request.session.get('attempt_id')
    question_ids = request.session.get('quiz_questions')

    if not attempt_id:
        ongoing_attempt = QuizAttempt.objects.filter(
            user=request.user, quiz=quiz, status='진행중'
        ).last()
        
        if ongoing_attempt:
            attempt_id = ongoing_attempt.id
            question_ids = list(quiz.questions.values_list('id', flat=True))
            request.session['attempt_id'] = attempt_id
            request.session['quiz_questions'] = question_ids
        else:
            # 새 시도 생성
            new_attempt = QuizAttempt.objects.create(user=request.user, quiz=quiz)
            attempt_id = new_attempt.id
            question_ids = list(quiz.questions.values_list('id', flat=True))
            request.session['attempt_id'] = attempt_id
            request.session['quiz_questions'] = question_ids
    
    attempt = get_object_or_404(QuizAttempt, pk=attempt_id)

    if attempt.status == '완료됨':
        messages.info(request, "이미 완료된 시험입니다.")
        last_result = QuizResult.objects.filter(quiz=quiz, student=request.user).last()
        if last_result:
            return redirect('quiz:exam_result', result_id=last_result.id)
        return redirect('quiz:index')

    # 문제 목록 로드
    if question_ids:
        questions_qs = Question.objects.filter(pk__in=question_ids)
        questions_dict = {q.id: q for q in questions_qs}
        ordered_questions = [questions_dict[qid] for qid in question_ids if qid in questions_dict]
    else:
        ordered_questions = list(quiz.questions.all())


    # -----------------------------------------------------------
    # [POST] 제출 및 자동 채점 (100점 만점 환산)
    # -----------------------------------------------------------
    if request.method == 'POST':
        with transaction.atomic():
            result = QuizResult.objects.create(
                student=request.user,
                quiz=quiz,
                score=0,
                submitted_at=timezone.now()
            )

            # [핵심 로직] 전체 문제 수에 따른 배점 계산
            total_count = len(ordered_questions)
            if total_count > 0:
                score_per_question = 100 / total_count  # 예: 20문제면 5.0점
            else:
                score_per_question = 0

            earned_score_float = 0.0  # 정밀한 계산을 위해 소수점으로 합산
            
            for question in ordered_questions:
                # 1문제당 배점 (자동 계산된 값 사용)
                current_score = score_per_question 
                
                user_input_single = request.POST.get(f'question_{question.id}')
                user_responses = request.POST.getlist(f'question_{question.id}')

                is_correct = False
                user_answer_text = ""

                # (A) 객관식 & OX
                if question.question_type in ['multiple_choice', 'true_false', '객관식']:
                    if user_input_single:
                        user_answer_text = user_input_single
                        if question.question_type == 'true_false':
                            correct_choice = question.choice_set.filter(is_correct=True).first()
                            if correct_choice and correct_choice.choice_text == user_input_single:
                                is_correct = True
                        else:
                            try:
                                selected = Choice.objects.get(pk=user_input_single)
                                if selected.is_correct:
                                    is_correct = True
                            except Choice.DoesNotExist:
                                pass

                # (B) 다중선택
                elif question.question_type in ['multiple_select', '다중선택']:
                    if user_responses:
                        valid_ids = [x for x in user_responses if x.isdigit()]
                        user_answer_text = ",".join(valid_ids)
                        correct_ids = set(question.choice_set.filter(is_correct=True).values_list('id', flat=True))
                        user_ids = set(int(x) for x in valid_ids)
                        
                        if correct_ids == user_ids and len(user_ids) > 0:
                            is_correct = True

                # (C) 주관식
                elif question.question_type in ['short_answer', '주관식 (단일정답)', '주관식 (복수정답)']:
                    if user_input_single:
                        user_answer_text = user_input_single.strip()
                        correct_answers = question.choice_set.filter(is_correct=True).values_list('choice_text', flat=True)
                        for ans in correct_answers:
                            if ans.strip().lower() == user_answer_text.lower():
                                is_correct = True
                                break

                # 정답이면 배점만큼 추가
                if is_correct:
                    earned_score_float += current_score

                # 상세 답안 저장
                StudentAnswer.objects.create(
                    result=result,
                    question=question,
                    answer_text=user_answer_text,
                    is_correct=is_correct
                )

            # 최종 점수 저장 (소수점 반올림하여 정수로 저장)
            # 예: 99.9999... -> 100점
            result.score = int(round(earned_score_float))
            result.save()

            # 상태 업데이트
            attempt.status = '완료됨'
            attempt.completed_at = timezone.now()
            attempt.save()

            messages.success(request, f"제출 완료! 점수: {result.score}점")
            return redirect('quiz:exam_result', result_id=result.id)

    # -----------------------------------------------------------
    # [GET] 화면 렌더링
    # -----------------------------------------------------------
    for q in ordered_questions:
        choices = list(q.choice_set.all())
        random.shuffle(choices)
        q.shuffled_choices = choices

    context = {
        'quiz': quiz,
        'questions': ordered_questions,
        'attempt': attempt,
        'start_time': attempt.started_at.isoformat() if attempt.started_at else timezone.now().isoformat(),
        'is_in_test_mode': True,
    }

    return render(request, 'quiz/take_quiz.html', context)

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

            # [핵심 수정 1] Question 생성 시 'quiz' 인자 제거
            new_question = Question.objects.create(
                question_text=question_text,
                question_type=q_type,
                difficulty=difficulty
            )
            
            # [핵심 수정 2] 생성 후 M2M 관계 설정
            new_question.quizzes.add(target_quiz)

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
        print(f"Bulk Add Error: {e}") # 디버깅용
        return JsonResponse({'status': 'error', 'message': str(e)})


# =========================================================
# [2] 퀴즈 결과 처리 (quiz_results)
# =========================================================
@login_required
def quiz_results(request):
    # 세션에서 데이터 로드
    question_ids = request.session.get('quiz_questions', [])
    user_answers = request.session.get('user_answers', {})
    attempt_id = request.session.get('attempt_id')

    if not question_ids or not attempt_id:
        messages.error(request, "제출된 답안이 없습니다.")
        return redirect('quiz:index')

    attempt = get_object_or_404(QuizAttempt, pk=attempt_id)
    
    # 중복 제출 방지
    if attempt.status == '완료됨':
        return redirect('quiz:my_results_index')

    profile, created = Profile.objects.get_or_create(user=request.user)
    badges_before = set(profile.badges.values_list('id', flat=True))

    # 문제 순서대로 가져오기 (채점 정확성)
    questions_dict = {q.id: q for q in Question.objects.filter(pk__in=question_ids)}
    
    correct_answers = 0
    results_data = []

    # TestResult 가져오기 (start_quiz에서 만들었으므로 get)
    # 혹시 없으면 create (안전장치)
    test_result, _ = TestResult.objects.get_or_create(
        attempt=attempt, 
        defaults={'user': request.user, 'quiz': attempt.quiz, 'score': 0, 'is_pass': False}
    )

    for q_id in question_ids:
        question = questions_dict.get(q_id)
        if not question: continue

        q_id_str = str(q_id)
        user_answer = user_answers.get(q_id_str)
        is_correct = False
        selected_choice = None
        short_answer_text = None

        try:
            if question.question_type == '객관식':
                if user_answer:
                    selected_choice = Choice.objects.get(pk=user_answer)
                    if selected_choice.is_correct:
                        is_correct = True
            
            elif question.question_type == '다중선택':
                # 로직 유지
                correct_ids = set(question.choice_set.filter(is_correct=True).values_list('id', flat=True))
                user_ids = set(user_answer if isinstance(user_answer, list) else [])
                if correct_ids and correct_ids == user_ids:
                    is_correct = True
                short_answer_text = ", ".join(map(str, user_ids))

            elif question.question_type.startswith('주관식'):
                possible = question.choice_set.filter(is_correct=True).values_list('choice_text', flat=True)
                user_text = str(user_answer).strip().lower() if user_answer else ""
                short_answer_text = user_answer
                for ans in possible:
                    if user_text == ans.strip().lower():
                        is_correct = True
                        break
        except Exception:
            pass

        if is_correct:
            correct_answers += 1
        
        # 상세 답안 저장
        UserAnswer.objects.create(
            test_result=test_result,
            question=question,
            selected_choice=selected_choice,
            short_answer_text=short_answer_text,
            is_correct=is_correct
        )

        results_data.append({
            'question': question,
            'selected_choice': selected_choice,
            'short_answer_text': short_answer_text,
            'is_correct': is_correct
        })
    
    # 점수 계산
    total_questions = len(question_ids)
    score = int((correct_answers / total_questions) * 100) if total_questions > 0 else 0
    is_pass = (score >= 80)
    
    # 결과 업데이트
    test_result.score = score
    test_result.is_pass = is_pass
    test_result.save()

    # 3회 탈락 시 잠금 로직
    if not is_pass:
        fail_count = TestResult.objects.filter(user=request.user, quiz=attempt.quiz, is_pass=False).count()
        if fail_count >= 3:
            request.user.profile.status = 'counseling'
            request.user.profile.save()
            messages.warning(request, "⛔ 3회 불합격하여 계정이 '면담 필요' 상태로 전환되었습니다.")

    # 뱃지 부여 (함수 호출 주석 처리 또는 import 필요)
    try:
        from .utils import award_badges # 필요시 import 위치 조정
        award_badges(request.user, test_result)
    except ImportError:
        pass # award_badges 함수가 없으면 패스

    # [핵심 수정] Attempt 상태를 반드시 '완료됨'으로 변경해야 재응시가 꼬이지 않음
    attempt.status = '완료됨'
    attempt.save()

    # 뱃지 알림 계산
    profile.refresh_from_db()
    badges_after = set(profile.badges.values_list('id', flat=True))
    new_badge_ids = badges_after - badges_before
    newly_awarded_badges = Badge.objects.filter(id__in=new_badge_ids)

    # 2회 불합격 시 메일 발송 로직 (기존 유지)
    if not is_pass:
        fail_cnt_mail = TestResult.objects.filter(user=request.user, quiz=attempt.quiz, is_pass=False).count()
        if fail_cnt_mail == 2:
            try:
                failed_attempts = TestResult.objects.filter(user=request.user, quiz=attempt.quiz, is_pass=False).order_by('completed_at')
                if failed_attempts.count() >= 2:
                    d_fmt = '%Y-%m-%d %H:%M'
                    d1 = f"{failed_attempts[0].completed_at.strftime(d_fmt)} / {failed_attempts[0].score}점"
                    d2 = f"{failed_attempts[1].completed_at.strftime(d_fmt)} / {failed_attempts[1].score}점"
                    
                    if hasattr(request.user, 'profile') and request.user.profile.pl and request.user.profile.pl.email:
                        pl = request.user.profile.pl
                        subject = f"[CBT 경고] 교육생 면담 요청: {profile.name}"
                        message = (
                            f"{pl.name}님,\n\n"
                            f"귀하의 담당 교육생 {profile.name}이(가) '{attempt.quiz.title}' 시험에서 2회 불합격했습니다.\n\n"
                            f"1차: {d1}\n2차: {d2}\n\n면담 및 지도가 필요합니다."
                        )
                        send_mail(subject, message, os.environ.get('EMAIL_HOST_USER'), [pl.email], fail_silently=True)
            except Exception as e:
                print(f"Mail Error: {e}")

    context = {
        'results_data': results_data,
        'score': score,
        'total_questions': total_questions,
        'correct_answers': correct_answers,
        'newly_awarded_badges': newly_awarded_badges,
        'test_result': test_result,
        'is_pass': is_pass,
    }

    # 세션 정리 (다음 시험을 위해)
    request.session.pop('quiz_questions', None)
    request.session.pop('user_answers', None)
    request.session.pop('attempt_id', None)
    request.session.pop('current_test_result_id', None)

    return render(request, 'quiz/quiz_results.html', context)


# =========================================================
# [3] 엑셀 파일 업로드 (upload_quiz)
# =========================================================
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
                
                # [핵심 수정 1] Question 생성 시 'quiz' 인자 제거
                question = Question.objects.create(
                    question_text=row['question_text'],
                    question_type=q_type_db,
                    difficulty=row['difficulty']
                )
                
                # [핵심 수정 2] 생성 후 M2M 관계 설정
                question.quizzes.add(quiz)

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

    # [Step 1] 3시간 유효시간 체크
    if attempt.requested_at and (timezone.now() > attempt.requested_at + timedelta(hours=3)):
        attempt.delete()  # 권한 회수
        messages.error(request, "⏳ 시험 응시 유효시간(3시간)이 초과되어 취소되었습니다. 다시 신청해주세요.")
        return redirect('quiz:index')

    # [Step 2] 계정 잠금(Lock) 및 3차 제한 검사
    if profile.status in ['counseling', 'dropout']:
        messages.error(request, "⛔ 계정이 잠겨있어 시험을 시작할 수 없습니다. 매니저 면담이 필요합니다.")
        return redirect('quiz:index')

    # 3차 탈락 여부 확인
    fail_count = TestResult.objects.filter(user=request.user, quiz=quiz, is_pass=False).count()
    if fail_count >= 3:
        if profile.status == 'attending':
            profile.status = 'counseling'
            profile.save()
        messages.error(request, f"⛔ '{quiz.title}' 시험에 3회 불합격하여 응시가 제한됩니다. 매니저 면담 후 해제 가능합니다.")
        return redirect('quiz:index')

    # [Step 3] 상태 체크
    if attempt.status == '완료됨':
        existing_result = TestResult.objects.filter(attempt=attempt).last()
        if existing_result:
            return redirect('quiz:result_detail', result_id=existing_result.id)
        else:
            messages.info(request, "이미 완료된 시험입니다.")
            return redirect('quiz:my_results_index')

    if attempt.status != '승인됨':
        messages.error(request, "아직 승인되지 않았거나 유효하지 않은 시험입니다.")
        return redirect('quiz:index')

    # [문제 출제 로직]
    # *중요* TestResult 미리 생성 (기존 로직 유지)
    test_result, created = TestResult.objects.get_or_create(
        user=request.user,
        quiz=quiz,
        attempt=attempt,
        defaults={'score': 0, 'is_pass': False}
    )

    final_questions = []

    # 1. [지정 문제 세트] 방식
    if quiz.generation_method == 'fixed' and quiz.exam_sheet:
        final_questions = list(quiz.exam_sheet.questions.all())
    
    # 2. [랜덤 출제] 방식
    else:
        loop_targets = []
        target_tags = None
        
        if quiz.generation_method == 'random_tag':
            target_tags = quiz.required_tags.all()
            if not target_tags.exists():
                messages.error(request, "설정된 태그가 없습니다. 관리자에게 문의하세요.")
                return redirect('quiz:index')
            loop_targets = list(target_tags)
        else:
            loop_targets = ['ALL'] 

        # 난이도별 분배 로직
        total_slots = 25 
        count = len(loop_targets)
        if count == 0: count = 1
            
        base_quota = total_slots // count
        remainder = total_slots % count

        for i, target in enumerate(loop_targets):
            this_quota = base_quota + (1 if i < remainder else 0)

            if target == 'ALL':
                base_qs = quiz.questions.all()
            else:
                base_qs = Question.objects.filter(tags=target)

            pool_h = list(base_qs.filter(difficulty='상'))
            pool_m = list(base_qs.filter(difficulty='중'))
            pool_l = list(base_qs.filter(difficulty='하'))
            
            random.shuffle(pool_h)
            random.shuffle(pool_m)
            random.shuffle(pool_l)

            target_h = int(this_quota * 0.32) 
            target_l = int(this_quota * 0.32) 
            target_m = this_quota - target_h - target_l 

            selected_in_loop = []

            # A. [상]
            picked_h = pool_h[:target_h]
            selected_in_loop.extend(picked_h)
            target_m += (target_h - len(picked_h))

            # B. [하]
            picked_l = pool_l[:target_l]
            selected_in_loop.extend(picked_l)
            target_m += (target_l - len(picked_l))

            # C. [중]
            picked_m = pool_m[:target_m]
            selected_in_loop.extend(picked_m)
            missing_m = target_m - len(picked_m)

            if missing_m > 0:
                remaining_l = pool_l[len(picked_l):]
                fallback_l = remaining_l[:missing_m]
                selected_in_loop.extend(fallback_l)
                
                still_missing = missing_m - len(fallback_l)
                if still_missing > 0:
                    remaining_h = pool_h[len(picked_h):]
                    fallback_h = remaining_h[:still_missing]
                    selected_in_loop.extend(fallback_h)
            
            final_questions.extend(selected_in_loop)
            
        # 25개 미달 시 채우기
        if len(final_questions) < 25:
            needed = 25 - len(final_questions)
            current_ids = [q.id for q in final_questions]
            
            if quiz.generation_method == 'random_tag' and target_tags:
                extra_pool = list(Question.objects.filter(tags__in=target_tags).exclude(id__in=current_ids).distinct())
            else:
                extra_pool = list(quiz.questions.exclude(id__in=current_ids))
            
            random.shuffle(extra_pool)
            final_questions.extend(extra_pool[:needed])

    random.shuffle(final_questions)
    
    if not final_questions:
        messages.error(request, "출제할 문제가 없습니다.")
        return redirect('quiz:index')

    # ----------------------------------------------------------
    # [세션 저장] - 오류 수정 핵심 부분
    # ----------------------------------------------------------
    # 기존 세션 정리
    keys_to_clear = ['quiz_questions', 'attempt_id', 'user_answers', 'current_test_result_id']
    for key in keys_to_clear:
        if key in request.session:
            del request.session[key]

    # [수정] 복잡한 동적 키 대신 고정 키 사용 (take_quiz와 일치시킴)
    request.session['quiz_questions'] = [q.id for q in final_questions]
    request.session['attempt_id'] = attempt.id
    request.session['current_test_result_id'] = test_result.id # 필요시 사용
    request.session['user_answers'] = {}

    return redirect('quiz:take_quiz', quiz_id=quiz.id)

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
    
    # [수정] 여기서 target_profile을 정의해줘야 에러가 안 납니다!
    target_profile = attempt.user.profile 
    
    # 2. [핵심] 매니저의 공정과 교육생의 공정 비교 (최고 관리자는 제외)
    # 이제 target_profile 변수가 정의되었으므로 에러가 나지 않습니다.
    if not is_process_manager(request.user, target_profile):
        # 교수의 공정과 학생의 공정이 다르면 거절
        messages.error(request, f"🚫 본인 담당 공정({target_profile.process})의 교육생만 승인할 수 있습니다.")
        return redirect('quiz:dashboard')

    # 3. 승인 처리
    attempt.status = '승인됨'
    attempt.save()
    messages.success(request, f"{target_profile.name}님의 시험 요청을 승인했습니다.")
    
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

    # 1-1. 매니저 권한 및 티켓 확인 로직
    if not request.user.is_superuser and hasattr(request.user, 'profile') and request.user.profile.process:
        my_process_id = str(request.user.profile.process.id)
        
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

    # 2. [Base QuerySet]
    results = TestResult.objects.select_related('user__profile', 'quiz')
    profiles = Profile.objects.select_related('cohort', 'company', 'process')

    # 관리자 제외
    exclude_staff_condition = Q(user__is_superuser=False) & Q(is_manager=False) & Q(is_pl=False)
    profiles = profiles.filter(exclude_staff_condition)
    results = results.filter(user__profile__in=profiles)

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

    # 5. [심층 분석] (문제 은행 방식 대응)
    filtered_answers = UserAnswer.objects.filter(test_result__in=results)
    all_question_ids = filtered_answers.values_list('question', flat=True).distinct()

    incorrect_analysis = []
    
    for q_id in all_question_ids:
        try:
            question = Question.objects.get(pk=q_id)
            
            # 연결된 퀴즈 제목 가져오기 (M2M 대응)
            related_quizzes = ", ".join([q.title for q in question.quizzes.all()[:2]])
            if question.quizzes.count() > 2: related_quizzes += "..."
            
            q_total_attempts = filtered_answers.filter(question=question).count()
            q_wrong_attempts = filtered_answers.filter(question=question, is_correct=False).count()
            
            error_rate = (q_wrong_attempts / q_total_attempts) * 100 if q_total_attempts > 0 else 0
            
            # 분포도
            distribution = filtered_answers.filter(question=question).values(
                answer_text=Case(
                    When(selected_choice__isnull=False, then=F('selected_choice__choice_text')),
                    default=F('short_answer_text'),
                    output_field=CharField(),
                )
            ).annotate(count=Count('id')).order_by('-count')
            
            dist_labels = [d['answer_text'] if d['answer_text'] else '무응답' for d in distribution]
            dist_counts = [d['count'] for d in distribution]

            # 정답 텍스트
            correct_choices = question.choice_set.filter(is_correct=True).values_list('choice_text', flat=True)
            correct_text = ", ".join(correct_choices) if correct_choices else "없음"

            incorrect_analysis.append({
                'question_id': question.id,
                'quiz_title': related_quizzes, # [수정됨] M2M 필드 사용
                'question_text': question.question_text,
                'difficulty': question.difficulty,
                'total': q_total_attempts,
                'wrong': q_wrong_attempts,
                'rate': round(error_rate, 1),
                'correct_answer': correct_text,
                'dist_labels': json.dumps(dist_labels), 
                'dist_counts': json.dumps(dist_counts)
            })
        except Question.DoesNotExist:
            continue

    # 오답률 높은 순 정렬
    incorrect_analysis.sort(key=lambda x: (x['rate'], x['wrong']), reverse=True)

    # 6. [위험군 목록]
    at_risk_students = []
    for profile in profiles:
        user_results = results.filter(user=profile.user).order_by('-completed_at')
        if user_results.exists():
            user_avg = user_results.aggregate(Avg('score'))['score__avg'] or 0
            fail_count = user_results.filter(is_pass=False).count()
            
            if selected_student or (user_avg < 60 or fail_count >= 2):
                # 면담 여부 확인 (최신 시험 vs 최신 로그)
                last_test_date = user_results.first().completed_at
                last_log = StudentLog.objects.filter(
                    profile=profile, log_type='counseling'
                ).order_by('-created_at').first() # [수정] StudentLog 사용
                
                # 면담이 더 나중에 있었다면 해결된 것으로 간주 (단, 개별 조회시는 표시)
                if not selected_student and last_log and last_log.created_at > last_test_date:
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
    """
    교육생의 종합 데이터(성적, 평가, 특이사항, 근태)를 엑셀로 생성하여 
    브라우저에서 바로 다운로드하는 뷰
    """
    if not request.user.is_staff:
        return redirect('quiz:index')

    target_process_id = request.GET.get('process_id')
    
    # 1. 대상 프로필 조회 (성능 최적화)
    profiles = Profile.objects.select_related(
        'user', 'cohort', 'company', 'process', 'pl', 'final_assessment'
    ).prefetch_related(
        'user__testresult_set', 
        'badges', 
        'managerevaluation_set__selected_items', 
        'logs', 
        'dailyschedule_set__work_type'
    ).order_by('cohort__start_date', 'user__username')

    # 2. 권한 필터링 (기존의 티켓 로직 복원)
    my_process = None
    if hasattr(request.user, 'profile') and request.user.profile.process:
        my_process = request.user.profile.process

    if request.user.is_superuser:
        # 관리자는 선택한 공정 또는 전체 다운로드 가능
        if target_process_id and target_process_id != 'ALL':
            profiles = profiles.filter(process_id=target_process_id)
    else:
        # 매니저는 본인 공정만 가능 (또는 티켓 보유 시)
        if not my_process:
            messages.error(request, "본인 공정 정보가 없어 작업을 수행할 수 없습니다.")
            return redirect('quiz:dashboard')

        if target_process_id == 'ALL':
            # 전체 다운로드 권한 확인 (Global Ticket)
            global_ticket = ProcessAccessRequest.objects.filter(
                requester=request.user, target_process__isnull=True, status='approved'
            ).first()
            
            if global_ticket:
                global_ticket.status = 'expired' # 티켓 사용 처리
                global_ticket.save()
                # 필터링 없이 전체 profiles 다운로드
            else:
                messages.error(request, "⛔ 전체 데이터 다운로드 권한이 없습니다.")
                return redirect('quiz:dashboard')

        elif not target_process_id or str(target_process_id) == str(my_process.id):
            # 본인 공정 다운로드 (기본)
            profiles = profiles.filter(process=my_process)
            
        else:
            # 타 공정 티켓 확인 (Specific Ticket)
            access_ticket = ProcessAccessRequest.objects.filter(
                requester=request.user, target_process_id=target_process_id, status='approved'
            ).first()
            
            if access_ticket:
                profiles = profiles.filter(process_id=target_process_id)
                access_ticket.status = 'expired' # 티켓 사용 처리
                access_ticket.save()
            else:
                messages.error(request, "⛔ 해당 공정 접근 권한이 없습니다.")
                return redirect('quiz:dashboard')

    # 3. 엑셀 데이터 생성
    all_quizzes = Quiz.objects.all().order_by('title')
    data_list = []

    for profile in profiles:
        # 기본 정보
        row = {
            'ID': profile.user.username, 
            '이름': profile.name, 
            '사번': profile.employee_id,
            '기수': profile.cohort.name if profile.cohort else '-',
            '공정': profile.process.name if profile.process else '-',
            '상태': profile.get_status_display(),
            '누적 경고': profile.warning_count,
        }

        # 시험 점수 (1~3차)
        results = sorted(list(profile.user.testresult_set.all()), key=lambda x: x.completed_at)
        quiz_map = {}
        for r in results:
            if r.quiz_id not in quiz_map: quiz_map[r.quiz_id] = []
            quiz_map[r.quiz_id].append(r.score)
            
        for q in all_quizzes:
            atts = quiz_map.get(q.id, [])
            row[f"[{q.title}] 1차"] = atts[0] if len(atts) > 0 else '-'
            row[f"[{q.title}] 2차"] = atts[1] if len(atts) > 1 else '-'
            row[f"[{q.title}] 3차"] = atts[2] if len(atts) > 2 else '-'

        # 종합 평가
        fa = getattr(profile, 'final_assessment', None)
        row.update({
            '시험평균': fa.exam_avg_score if fa else 0,
            '실습': fa.practice_score if fa else 0,
            '노트': fa.note_score if fa else 0,
            '태도': fa.attitude_score if fa else 0,
            '최종점수': fa.final_score if fa else '-',
            '매니저의견': fa.manager_comment if fa else '-',
        })

        # 체크리스트
        last_eval = profile.managerevaluation_set.last()
        row['체크리스트'] = "\n".join([i.description for i in last_eval.selected_items.all()]) if last_eval else ""

        # 특이사항/경고 이력
        logs = profile.logs.all().order_by('created_at')
        log_txt = ""
        for l in logs:
            log_txt += f"[{l.created_at.date()}] {l.get_log_type_display()}: {l.reason}"
            if l.action_taken: log_txt += f" (조치: {l.action_taken})"
            log_txt += "\n"
        row['특이사항 이력'] = log_txt

        # 근태 요약
        schedules = profile.dailyschedule_set.all()
        w = schedules.filter(work_type__deduction=0).count()
        l = schedules.filter(work_type__deduction=1.0).count()
        row['근태'] = f"출근:{w} / 연차:{l}"
        
        data_list.append(row)

    # 4. 파일 생성 및 다운로드 (Direct Download)
    try:
        if not data_list:
            messages.warning(request, "다운로드할 데이터가 없습니다.")
            return redirect('quiz:manager_dashboard')

        df = pd.DataFrame(data_list)
        excel_file = BytesIO()

        # XlsxWriter 엔진 사용 (서식 적용)
        with pd.ExcelWriter(excel_file, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='종합_데이터')
            
            workbook = writer.book
            worksheet = writer.sheets['종합_데이터']
            
            # 셀 서식 (줄바꿈 및 정렬)
            format_wrap = workbook.add_format({'text_wrap': True, 'valign': 'top'})
            
            # 컬럼 너비 자동 조정
            for idx, col in enumerate(df.columns):
                if col in ['특이사항 이력', '체크리스트', '매니저의견']:
                    worksheet.set_column(idx, idx, 50, format_wrap)
                else:
                    worksheet.set_column(idx, idx, 15)
        
        # 파일 포인터 초기화
        excel_file.seek(0)

        # 파일명 설정 (한글 깨짐 방지)
        target_name = "전체"
        if target_process_id and target_process_id != 'ALL':
            try: target_name = Process.objects.get(pk=target_process_id).name
            except: pass
        elif my_process and not request.user.is_superuser:
            target_name = my_process.name

        filename = f"{target_name}_FullData_{timezone.now().strftime('%Y%m%d')}.xlsx"
        encoded_filename = urllib.parse.quote(filename)

        # HTTP 응답 생성 (다운로드 트리거)
        response = HttpResponse(
            excel_file.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f"attachment; filename*=UTF-8''{encoded_filename}"
        
        messages.success(request, "엑셀 다운로드가 시작되었습니다.")
        return response

    except Exception as e:
        messages.error(request, f"엑셀 생성 중 오류 발생: {str(e)}")
        return redirect('quiz:manager_dashboard')

    # 3. 엑셀 데이터 생성 시작
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

        # (C) 종합 평가 데이터 (FinalAssessment)
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
        # 가장 최근 평가서 1개를 가져옴
        last_eval = profile.managerevaluation_set.order_by('-created_at').first()
        checklist_str = ""
        if last_eval:
            items = last_eval.selected_items.all()
            # 엑셀 셀 하나에 줄바꿈으로 넣기 위해 join 사용
            checklist_str = "\n".join([f"[{'긍정' if item.is_positive else '부정'}] {item.description}" for item in items])
        row_data['체크리스트 평가'] = checklist_str

        # (E) 특이사항/경고 이력 (StudentLog)
        logs = profile.logs.all().order_by('created_at')
        log_str = ""
        for log in logs:
            log_str += f"[{log.created_at.strftime('%Y-%m-%d')}] {log.get_log_type_display()}: {log.reason}\n"
        row_data['특이사항/경고 이력'] = log_str

        # (F) 근태 요약 (DailySchedule)
        # WorkType의 deduction(차감) 값을 기준으로 카운트
        schedules = profile.dailyschedule_set.all()
        
        work_cnt = schedules.filter(work_type__deduction=0).count() # 정상출근
        leave_cnt = schedules.filter(work_type__deduction=1.0).count() # 연차
        half_cnt = schedules.filter(work_type__deduction=0.5).count() # 반차
        
        row_data['근태 요약'] = f"출근:{work_cnt} / 연차:{leave_cnt} / 반차:{half_cnt}"
        
        # (G) 뱃지 정보
        badge_count = profile.badges.count()
        badge_list = ", ".join([b.name for b in profile.badges.all()])
        row_data['획득 뱃지 수'] = badge_count
        row_data['뱃지 목록'] = badge_list

        data_list.append(row_data)

    # 4. 엑셀 파일 생성 및 발송
    try:
        if not data_list:
            messages.warning(request, "다운로드할 데이터가 없습니다.")
            return redirect('quiz:manager_dashboard')

        df = pd.DataFrame(data_list)
        excel_file = BytesIO()
        
        # XlsxWriter 엔진 사용 (서식 적용을 위해)
        with pd.ExcelWriter(excel_file, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='종합_데이터')
            
            workbook = writer.book
            worksheet = writer.sheets['종합_데이터']
            
            # 셀 줄바꿈 포맷 (특이사항 등이 길어질 수 있으므로)
            format_wrap = workbook.add_format({'text_wrap': True, 'valign': 'top'})
            
            # 컬럼 너비 자동 조정 (대략적으로 설정)
            for idx, col in enumerate(df.columns):
                if col in ['특이사항/경고 이력', '체크리스트 평가', '매니저 종합 의견']:
                    worksheet.set_column(idx, idx, 50, format_wrap) # 너비 50 & 줄바꿈
                elif col in ['사용자 ID', '이름', '이메일']:
                    worksheet.set_column(idx, idx, 20)
                else:
                    worksheet.set_column(idx, idx, 12)

        excel_file.seek(0)

        # 파일명 설정
        target_name = "전체"
        if target_process_id and target_process_id != 'ALL':
            try: target_name = Process.objects.get(pk=target_process_id).name
            except: pass
        elif my_process and not request.user.is_superuser:
            target_name = my_process.name

        subject = f"[보안] {request.user.profile.name}님 요청 데이터 ({target_name})"
        body = (
            f"요청하신 교육생 데이터입니다.\n"
            f"요청자: {request.user.profile.name}\n"
            f"대상 공정: {target_name}\n\n"
            f"* 포함 내역: 기본정보, 시험성적(1~3차), 종합평가(점수/석차), 체크리스트, 특이사항/경고 이력, 근태 요약, 뱃지 현황"
        )
        
        email = EmailMessage(
            subject, body, settings.EMAIL_HOST_USER, [request.user.email]
        )
        filename = f"{target_name}_FullData_{timezone.now().strftime('%Y%m%d')}.xlsx"
        email.attach(filename, excel_file.read(), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        email.send()
        
        messages.success(request, f"✅ 상세 데이터가 포함된 엑셀 파일이 '{request.user.email}'로 발송되었습니다.")

    except Exception as e:
        print(f"Mail Error: {e}")
        messages.error(request, f"메일 발송 중 오류가 발생했습니다: {str(e)}")

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
    """
    매니저 대시보드: 각종 요청 및 현황 요약
    """
    user = request.user
    
    # 0. 권한 체크 (스태프, 매니저, PL 중 하나여야 함)
    if not (user.is_staff or (hasattr(user, 'profile') and (user.profile.is_manager or user.profile.is_pl))):
        messages.error(request, "접근 권한이 없습니다.")
        return redirect('quiz:index')

    # -----------------------------------------------------------
    # 1. 가입 승인 대기 (전체 대상 - 관리자 공통)
    # -----------------------------------------------------------
    signup_pending_count = User.objects.filter(is_active=False).count()
    
    # -----------------------------------------------------------
    # 2. 시험 응시 대기 (내 공정)
    # -----------------------------------------------------------
    exam_q = Q(status='대기중')
    if not user.is_superuser and hasattr(user, 'profile') and user.profile.process:
        exam_q &= Q(user__profile__process=user.profile.process)
    exam_pending_count = QuizAttempt.objects.filter(exam_q).count()

    # -----------------------------------------------------------
    # 3. 위험군 (잠금 상태 - counseling)
    # -----------------------------------------------------------
    risk_q = Q(status='counseling')
    if not user.is_superuser and hasattr(user, 'profile') and user.profile.process:
        risk_q &= Q(process=user.profile.process)
    risk_count = Profile.objects.filter(risk_q).count()

    # -----------------------------------------------------------
    # 4. 권한 요청 대기 (타 매니저 -> 나)
    # -----------------------------------------------------------
    access_req_count = 0
    try:
        # 관리자는 전체, 매니저는 내 공정으로 온 요청만
        if user.is_superuser:
            access_req_count = ProcessAccessRequest.objects.filter(status='pending').count()
        elif hasattr(user, 'profile') and user.profile.process:
            access_req_count = ProcessAccessRequest.objects.filter(
                target_process=user.profile.process, status='pending'
            ).count()
    except NameError: 
        pass # 모델이 아직 없거나 import 안 된 경우 패스

    # -----------------------------------------------------------
    # 5. 근무표 변경 요청 대기
    # -----------------------------------------------------------
    schedule_pending_count = 0
    if hasattr(user, 'profile'):
        try:
            from attendance.models import ScheduleRequest # 지연 import
            if user.is_superuser:
                schedule_pending_count = ScheduleRequest.objects.filter(status='pending').count()
            elif user.profile.is_manager:
                schedule_pending_count = ScheduleRequest.objects.filter(
                    requester__process=user.profile.process, status='pending'
                ).exclude(requester=user.profile).count()
        except ImportError:
            pass

    # -----------------------------------------------------------
    # [신규 추가] 6. 면담 필요 (미해결 상담 요청)
    # -----------------------------------------------------------
    # 조건: 상담(counseling) 타입이면서 + 아직 해결되지 않은(is_resolved=False) 건
    counseling_q = Q(log_type='counseling', is_resolved=False)
    
    # 관리자가 아니고 내 공정이 있다면 -> 내 공정 학생들의 요청만 카운트
    if not user.is_superuser and hasattr(user, 'profile') and user.profile.process:
        counseling_q &= Q(profile__process=user.profile.process)
        
    counseling_count = StudentLog.objects.filter(counseling_q).count()

    # -----------------------------------------------------------
    # 템플릿 렌더링
    # -----------------------------------------------------------
    return render(request, 'quiz/manager/dashboard_main.html', {
        'signup_pending_count': signup_pending_count,
        'exam_pending_count': exam_pending_count,
        'risk_count': risk_count,
        'access_req_count': access_req_count,
        'schedule_pending_count': schedule_pending_count,
        'counseling_count': counseling_count, # [추가됨] 템플릿에서 {{ counseling_count }} 사용 가능
    })

@login_required
def manager_trainee_list(request):
    if not request.user.is_staff: return redirect('quiz:index')

    # 현재 기수 자동 선택
    today = timezone.now().date()
    active_cohort = Cohort.objects.filter(start_date__lte=today, end_date__gte=today).first()
    default_cohort_id = active_cohort.id if active_cohort else ''

    data = request.GET.copy()
    if 'cohort' not in data and default_cohort_id:
        data['cohort'] = default_cohort_id

    form = TraineeFilterForm(data)
    profiles = Profile.objects.select_related('user', 'cohort', 'process').exclude(
        user__is_superuser=True, is_manager=True
    ).order_by('cohort__start_date', 'name')

    if form.is_valid():
        if form.cleaned_data['cohort']: profiles = profiles.filter(cohort=form.cleaned_data['cohort'])
        if form.cleaned_data['process']: profiles = profiles.filter(process=form.cleaned_data['process'])
        if form.cleaned_data['status']: profiles = profiles.filter(status=form.cleaned_data['status'])
        if form.cleaned_data['search']:
            q = form.cleaned_data['search']
            profiles = profiles.filter(Q(name__icontains=q)|Q(employee_id__icontains=q)|Q(user__username__icontains=q))

    paginator = Paginator(profiles, 50)
    page_obj = paginator.get_page(request.GET.get('page'))
    pending_users = User.objects.filter(is_active=False).order_by('-date_joined')

    return render(request, 'quiz/manager/trainee_list.html', {
        'form': form, 'profiles': page_obj, 'pending_users': pending_users,
        'total_count': profiles.count()
    })

@login_required
def manager_trainee_detail(request, profile_id):
    if not request.user.is_staff: return redirect('quiz:index')
    profile = get_object_or_404(Profile, pk=profile_id)
    results = TestResult.objects.filter(user=profile.user).order_by('-completed_at')
    # [수정] StudentLog 사용
    logs = StudentLog.objects.filter(profile=profile).order_by('-created_at')
    
    return render(request, 'quiz/manager/trainee_detail.html', {
        'profile': profile, 'results': results, 'logs': logs, 'badges': profile.badges.all()
    })

# -----------------------------------------------------------
# [핵심] 특이사항/경고/징계 로직 (1~4단계 자동화)
# -----------------------------------------------------------
@login_required
def manage_student_logs(request, profile_id):
    if not request.user.is_staff: return redirect('quiz:index')
    profile = get_object_or_404(Profile, pk=profile_id)
    logs = profile.logs.all()

    if request.method == 'POST':
        form = StudentLogForm(request.POST)
        if form.is_valid():
            log = form.save(commit=False)
            log.profile = profile
            log.created_by = request.user  # <--- recorder 아님! created_by로 수정
            
            # [A] 일반 경고 (누적 로직)
            if log.log_type == 'warning':
                profile.warning_count += 1
                log.save()
                
                # 2회: 1차 경고장 (자동) -> 잠금
                if profile.warning_count == 2:
                    StudentLog.objects.create(
                        profile=profile, recorder=request.user, log_type='warning_letter', 
                        reason="[시스템 자동] 경고 2회 누적 -> 1차 경고장 발부",
                        action_taken="계정 잠금 (매니저 면담 필요)"
                    )
                    profile.status = 'counseling'
                    messages.warning(request, "⚠️ 경고 2회 누적! 1차 경고장이 발부되고 계정이 잠겼습니다.")

                # 3회: 2차 경고장 (자동) -> 잠금 (PL 면담 필수)
                elif profile.warning_count == 3:
                    StudentLog.objects.create(
                        profile=profile, recorder=request.user, log_type='warning_letter', 
                        reason="[시스템 자동] 경고 3회 누적 -> 2차 경고장 발부",
                        action_taken="계정 잠금 (PL 면담 필수)"
                    )
                    profile.status = 'counseling'
                    messages.error(request, "🚫 경고 3회 누적! 2차 경고장이 발부되었습니다. (PL 면담 필수)")

                # 4회 이상: 퇴소
                elif profile.warning_count >= 4:
                    profile.status = 'dropout'
                    messages.error(request, "⛔ 경고 4회 누적! 퇴소 처리되었습니다.")
                
                # 1회: 주의
                else:
                    profile.status = 'caution'
                    messages.info(request, "일반 경고가 등록되었습니다. (상태: 주의)")

            # [B] 경고장 즉시 발부 (중대 과실 - 점프)
            elif log.log_type == 'warning_letter':
                if profile.warning_count < 2: profile.warning_count = 2
                else: profile.warning_count += 1
                
                profile.status = 'counseling'
                if profile.warning_count >= 4: profile.status = 'dropout'
                
                log.save()
                messages.warning(request, f"⛔ 경고장이 즉시 발부되었습니다. (현재 누적: {profile.warning_count}회)")

            # [C] 면담 및 조치 (잠금 해제)
            elif log.log_type == 'counseling':
                is_resolve = request.POST.get('resolve_lock') == 'on'
                pl_check = request.POST.get('pl_check') == 'on'
                
                if is_resolve:
                    # 3회 누적자(2차 경고장)는 PL 체크 필수
                    if profile.warning_count == 3 and not pl_check:
                         messages.error(request, "🚫 3회 누적자는 'PL 면담 확인'을 체크해야 잠금이 해제됩니다.")
                         return redirect('quiz:manage_student_logs', profile_id=profile.id)

                    log.is_resolved = True
                    if profile.warning_count >= 4:
                        profile.status = 'dropout'
                        messages.warning(request, "퇴소 대상자는 잠금을 해제할 수 없습니다.")
                    else:
                        profile.status = 'attending'
                        messages.success(request, "✅ 조치가 완료되어 계정이 정상화되었습니다.")
                
                log.save()

            else:
                log.save()
                messages.success(request, "기록되었습니다.")

            profile.save()
            return redirect('quiz:manage_student_logs', profile_id=profile.id)
    else:
        form = StudentLogForm()

    return render(request, 'quiz/manager/manage_student_logs.html', {
        'profile': profile, 'logs': logs, 'form': form
    })

# [매니저 모달용 간편 작성]
@login_required
@require_POST
def manager_create_counseling_log(request, profile_id):
    if not request.user.is_staff: return JsonResponse({'status': 'error'}, status=403)
    try:
        profile = get_object_or_404(Profile, pk=profile_id)
        content = request.POST.get('content')
        opinion = request.POST.get('opinion')
        is_passed = request.POST.get('is_passed') == 'on'
        
        StudentLog.objects.create(
            profile=profile, recorder=request.user, log_type='counseling',
            reason=content, action_taken=opinion, is_resolved=is_passed
        )
        if is_passed and profile.status == 'counseling':
            profile.status = 'attending'; profile.save()
        
        return JsonResponse({'status': 'success', 'message': '저장되었습니다.'})
    except Exception as e: return JsonResponse({'status': 'error', 'message': str(e)})


# --- (기타 액션 함수들: 가입승인, 비번초기화 등 기존 유지) ---
@login_required
@require_POST
def approve_signup_bulk(request):
    if not request.user.is_staff: return JsonResponse({'status':'error'}, status=403)
    data = json.loads(request.body)
    users = User.objects.filter(id__in=data.get('user_ids', []))
    if data.get('action') == 'approve':
        users.update(is_active=True)
        return JsonResponse({'status':'success', 'message': f'{users.count()}명 승인 완료'})
    else:
        users.delete()
        return JsonResponse({'status':'success', 'message': '거절 완료'})

@login_required
@require_POST
def reset_password_bulk(request):
    if not request.user.is_staff: return JsonResponse({'status':'error'}, status=403)
    data = json.loads(request.body)
    users = User.objects.filter(id__in=data.get('user_ids', []))
    for u in users:
        u.set_password('1234')
        if hasattr(u, 'profile'): u.profile.must_change_password = True; u.profile.save()
        u.save()
    return JsonResponse({'status':'success', 'message': '초기화 완료'})

@login_required
@require_POST
def unlock_account(request, profile_id):
    if not request.user.is_staff: return JsonResponse({'status':'error'}, status=403)
    p = get_object_or_404(Profile, pk=profile_id)
    if p.status in ['counseling', 'dropout']:
        p.status = 'attending'; p.save()
        return JsonResponse({'status':'success', 'message': '해제 완료'})
    return JsonResponse({'status':'info', 'message': '이미 정상입니다.'})




# 7. 응시 요청 관리 페이지
@login_required
def manager_exam_requests(request):
    """
    시험 응시 요청 및 공정 조회 권한 요청을 한 곳에서 관리하는 뷰
    """
    if not request.user.is_staff: return redirect('quiz:index')

    # 1. 시험 응시 요청 (QuizAttempt)
    if not request.user.is_superuser and hasattr(request.user, 'profile') and request.user.profile.process:
        exam_reqs = QuizAttempt.objects.filter(
            status='대기중', 
            user__profile__process=request.user.profile.process
        ).order_by('requested_at')
    else:
        exam_reqs = QuizAttempt.objects.filter(status='대기중').order_by('requested_at')

    # 2. [신규 추가] 권한 조회 요청 (ProcessAccessRequest)
    access_reqs = []
    try:
        # 관리자: 모든 요청 확인
        if request.user.is_superuser:
            access_reqs = ProcessAccessRequest.objects.filter(status='pending').order_by('created_at')
        # 매니저: 내 공정에 대한 요청만 확인
        elif hasattr(request.user, 'profile') and request.user.profile.process:
            access_reqs = ProcessAccessRequest.objects.filter(
                target_process=request.user.profile.process,
                status='pending'
            ).order_by('created_at')
    except NameError:
        pass

    return render(request, 'quiz/manager/exam_requests.html', {
        'requests': exam_reqs,       # 시험 요청
        'access_requests': access_reqs # 권한 요청 (추가됨)
    })

# 1. PL 대시보드
@login_required
def pl_dashboard(request):
    # (1) 권한 체크
    if not (request.user.is_staff and (request.user.profile.is_pl or request.user.is_superuser)):
        messages.error(request, "접근 권한이 없습니다.")
        return redirect('quiz:index')
    
    # (2) 기본 대상 설정
    if request.user.is_superuser:
        trainees = Profile.objects.select_related('user', 'cohort', 'process').all()
    else:
        try:
            pl_obj = PartLeader.objects.get(email=request.user.email)
            trainees = Profile.objects.filter(pl=pl_obj).select_related('user', 'cohort', 'process')
        except PartLeader.DoesNotExist:
            trainees = Profile.objects.none()

    # (3) 검색 및 필터링
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
        'cohorts': Cohort.objects.all(),
        'processes': Process.objects.all(),
        'sel_q': search_query,
        'sel_cohort': int(filter_cohort) if filter_cohort else '',
        'sel_process': int(filter_process) if filter_process else '',
    }
    return render(request, 'quiz/pl_dashboard.html', context)


# 2. [핵심 수정] PL 교육생 상세 리포트 (중복 제거 및 HTML 렌더링 적용)
@login_required
def pl_trainee_detail(request, profile_id):
    """
    PL용 교육생 상세 리포트
    - 태도/역량: 매니저 평가서 체크리스트
    - 특이사항: 경고 횟수 및 재시험 과목 수 계산
    - AI 분석: 퀴즈 결과 기반 태그별 정답률 분석 (UserAnswer 필드명 수정됨)
    """
    # 1. 권한 체크
    if not (request.user.is_superuser or (hasattr(request.user, 'profile') and request.user.profile.is_pl)):
         return redirect('quiz:index')

    profile = get_object_or_404(Profile, pk=profile_id)
    
    # 2. 시험 결과 (최신순)
    # [확인 완료] 슬라이싱 없이 전체 데이터를 가져옵니다. (HTML 스크롤바 사용)
    results = TestResult.objects.filter(user=profile.user).select_related('quiz').order_by('-completed_at')
    
    # 3. AI 분석 (태그 필터링)
    # (1) 사용자가 응시한 퀴즈 ID 목록
    taken_quiz_ids = results.values_list('quiz_id', flat=True).distinct()
    
    # (2) 해당 퀴즈들에 포함된 질문들 (Question-Quiz 관계가 N:M일 경우 quizzes__in 사용)
    relevant_questions = Question.objects.filter(quizzes__in=taken_quiz_ids).distinct()
    
    # (3) 그 질문들에 달린 태그들
    relevant_tags = Tag.objects.filter(question__in=relevant_questions).distinct()
    
    tag_analysis = []
    for tag in relevant_tags:
        # [수정] attempt__user -> test_result__user (모델 필드명 일치)
        total = UserAnswer.objects.filter(
            test_result__user=profile.user, 
            question__tags=tag
        ).count()
        
        if total > 0:
            correct = UserAnswer.objects.filter(
                test_result__user=profile.user, 
                question__tags=tag, 
                is_correct=True
            ).count()
            
            accuracy = (correct / total) * 100
            tag_analysis.append({
                'name': tag.name, 
                'accuracy': accuracy, 
                'status': 'weak' if accuracy < 60 else 'strong' if accuracy >= 80 else 'normal'
            })
    
    # 정답률 높은 순으로 정렬
    tag_analysis.sort(key=lambda x: x['accuracy'], reverse=True)

    # 4. 태도 및 역량 (매니저 평가 체크리스트)
    manager_eval = ManagerEvaluation.objects.filter(trainee_profile=profile).last()
    checklist_items = []
    if manager_eval:
        checklist_items = manager_eval.selected_items.all().select_related('category').order_by('category__order')

    # 5. 특이사항 통계 (경고 및 재시험)
    # (A) 경고/경고장 횟수
    warning_count = StudentLog.objects.filter(profile=profile, log_type='warning').count()
    warning_letter_count = StudentLog.objects.filter(profile=profile, log_type='warning_letter').count()
    
    # (B) 재시험 횟수 계산 (과목별 응시 횟수 집계)
    quiz_counts = TestResult.objects.filter(user=profile.user).values('quiz').annotate(attempt_cnt=Count('id'))
    
    retake_2_count = 0 
    retake_3_count = 0 
    
    for q in quiz_counts:
        if q['attempt_cnt'] >= 2:
            retake_2_count += 1
        if q['attempt_cnt'] >= 3:
            retake_3_count += 1

    context = {
        'profile': profile,
        'results': results, # [재확인] 전체 목록 전달
        'tag_analysis': tag_analysis,
        'manager_eval': manager_eval,
        'checklist_items': checklist_items,
        'warning_count': warning_count,
        'warning_letter_count': warning_letter_count,
        'retake_2_count': retake_2_count,
        'retake_3_count': retake_3_count,
    }
    
    return render(request, 'quiz/pl_trainee_detail.html', context)

# 3. PL 리포트 출력 뷰 (인쇄용)
@login_required
def pl_report_view(request):
    if not (request.user.is_staff and (request.user.profile.is_pl or request.user.is_superuser)):
        messages.error(request, "접근 권한이 없습니다.")
        return redirect('quiz:index')

    if request.user.is_superuser:
        trainees = Profile.objects.select_related('user', 'cohort', 'process').all()
    else:
        try:
            pl_obj = PartLeader.objects.get(email=request.user.email)
            trainees = Profile.objects.filter(pl=pl_obj).select_related('user', 'cohort', 'process')
        except PartLeader.DoesNotExist:
            trainees = Profile.objects.none()

    # 데이터 구성
    all_quizzes = Quiz.objects.all().order_by('title')
    report_data = []

    for t in trainees:
        results = t.user.testresult_set.all().order_by('completed_at')
        scores_list = []
        for quiz in all_quizzes:
            attempts = results.filter(quiz=quiz)
            s1 = attempts[0].score if attempts.count() >= 1 else '-'
            s2 = attempts[1].score if attempts.count() >= 2 else '-'
            s3 = attempts[2].score if attempts.count() >= 3 else '-'
            scores_list.append({'title': quiz.title, 's1': s1, 's2': s2, 's3': s3})
        
        fa = getattr(t, 'final_assessment', None)
        report_data.append({
            'profile': t,
            'scores': scores_list,
            'assessment': {
                'final_score': fa.final_score if fa else '-',
                'rank': fa.rank if fa else '-',
                'comment': fa.manager_comment if fa else "의견 없음"
            }
        })

    return render(request, 'quiz/pl_report_print.html', {'report_data': report_data, 'today': timezone.now().date()})

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
    if not request.user.is_staff: 
        return redirect('quiz:index')
    
    # 관리자는 전체 보기
    if request.user.is_superuser:
        quizzes = Quiz.objects.all().order_by('-id')

    # 매니저는 (공통 + 자기공정) 보기
    elif hasattr(request.user, 'profile') and request.user.profile.process:
        my_process = request.user.profile.process
        quizzes = Quiz.objects.filter(
            # [수정] associated_process -> related_process 로 변경
            Q(category=Quiz.Category.COMMON) | Q(related_process=my_process)
        ).distinct().order_by('-id')

    else:
        # 공정 정보가 없는 매니저는 공통만 보기
        quizzes = Quiz.objects.filter(category=Quiz.Category.COMMON).order_by('-id')

    return render(request, 'quiz/manager/quiz_list.html', {'quizzes': quizzes})

# ==================================================================
# 1. 시험 생성 함수 (Create) - 수동 처리 방식
# ==================================================================
@login_required
def quiz_create(request):
    # 관리자 권한 체크
    if not request.user.is_staff:
        messages.error(request, "관리자 권한이 필요합니다.")
        return redirect('quiz:index')

    # [POST 요청] 데이터 저장
    if request.method == 'POST':
        try:
            # (1) 텍스트 데이터 가져오기
            title = request.POST.get('title')
            description = request.POST.get('description')
            category = request.POST.get('category')
            
            # [수정 1] 공정 ID를 받아서 실제 Process 객체로 변환
            process_id = request.POST.get('related_process')
            process_instance = None
            
            # 공정이 선택되었고, 빈 문자열이 아닐 경우에만 DB 조회
            if process_id and process_id.strip():
                process_instance = Process.objects.filter(id=process_id).first()

            # (2) 숫자 데이터 처리 (빈 값일 경우 기본값 설정)
            # HTML input에서 값이 넘어오지 않을 경우를 대비해 default 값 지정
            q_count = request.POST.get('question_count') or 25
            p_score = request.POST.get('pass_score') or 80
            t_limit = request.POST.get('time_limit') or 30

            # (3) DB에 저장 (Quiz 객체 생성)
            new_quiz = Quiz.objects.create(
                title=title,
                description=description,
                category=category,
                related_process=process_instance,  # 객체 저장 (없으면 None)
                question_count=int(q_count),
                pass_score=int(p_score),
                time_limit=int(t_limit),
                created_by=request.user
            )

            messages.success(request, f"새 시험 '{title}'이(가) 생성되었습니다.")
            # 생성 후 문제 목록(관리) 화면으로 이동
            return redirect('quiz:question_list', quiz_id=new_quiz.id)

        except Exception as e:
            print(f"Quiz Create Error: {e}")
            messages.error(request, "시험 생성 중 오류가 발생했습니다. 입력값을 확인해주세요.")

    # [GET 요청] 생성 화면 표시
    # [수정 2] 공정 목록(processes)을 전달하여 드롭다운(<select>) 구성
    processes = Process.objects.all()
    
    return render(request, 'quiz/manager/quiz_form.html', {
        'title': '새 시험 생성', 
        'processes': processes
    })


# ==================================================================
# 2. 시험 수정 함수 (Update) - 수동 처리 방식
# ==================================================================
@login_required
def quiz_update(request, quiz_id):
    # 관리자 권한 체크
    if not request.user.is_staff:
        messages.error(request, "권한이 없습니다.")
        return redirect('quiz:index')
    
    quiz = get_object_or_404(Quiz, pk=quiz_id)

    # [POST 요청] 데이터 수정
    if request.method == 'POST':
        try:
            # (1) 기본 정보 업데이트
            quiz.title = request.POST.get('title')
            quiz.description = request.POST.get('description')
            quiz.category = request.POST.get('category')
            
            # [수정 1] 공정 객체 업데이트 로직
            process_id = request.POST.get('related_process')
            if process_id and process_id.strip():
                quiz.related_process = Process.objects.filter(id=process_id).first()
            else:
                # '선택 안함'인 경우 연결 해제
                quiz.related_process = None

            # (2) 숫자 데이터 업데이트
            q_count = request.POST.get('question_count') or 25
            p_score = request.POST.get('pass_score') or 80
            t_limit = request.POST.get('time_limit') or 30

            quiz.question_count = int(q_count)
            quiz.pass_score = int(p_score)
            quiz.time_limit = int(t_limit)

            # (3) 저장
            quiz.save()
            
            messages.success(request, "시험 설정이 수정되었습니다.")
            return redirect('quiz:manager_quiz_list')

        except Exception as e:
            print(f"Quiz Update Error: {e}")
            messages.error(request, "수정 중 오류가 발생했습니다.")

    # [GET 요청] 수정 화면 표시
    # [수정 2] 기존 데이터(quiz)와 공정 목록(processes) 함께 전달
    processes = Process.objects.all()
    
    return render(request, 'quiz/manager/quiz_form.html', {
        'quiz': quiz,
        'title': '시험 설정 수정',
        'processes': processes
    })

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
    
    # [수정됨] 1:N 방식(question_set) -> M:N 방식(questions)으로 변경
    # 이제 문제는 'quiz.questions'를 통해 가져와야 합니다.
    questions = quiz.questions.all().order_by('-created_at')
    
    return render(request, 'quiz/manager/question_list.html', {'quiz': quiz, 'questions': questions})

# ------------------------------------------------------------------
# 문제 등록 (Create)
# ------------------------------------------------------------------
@login_required
def question_create(request, quiz_id):
    if not request.user.is_staff:
        return redirect('quiz:index')
    
    quiz = get_object_or_404(Quiz, pk=quiz_id)

    if request.method == 'POST':
        try:
            # 1. 문제 생성
            question = Question.objects.create(
                question_text=request.POST.get('question_text'),
                question_type=request.POST.get('question_type'),
                difficulty=request.POST.get('difficulty')
            )
            question.quizzes.add(quiz)

            if request.FILES.get('question_image'):
                question.image = request.FILES['question_image']
                question.save()

            # 2. 태그 저장 (JSON 파싱 + 일반 콤마 지원)
            tags_input = request.POST.get('tags', '')
            if tags_input:
                try:
                    # Tagify가 보낸 JSON ([{"value":"태그1"}]) 처리
                    tag_list = json.loads(tags_input)
                    for item in tag_list:
                        t_name = item.get('value', '').strip()
                        if t_name:
                            tag_obj, _ = Tag.objects.get_or_create(name=t_name)
                            question.tags.add(tag_obj)
                except json.JSONDecodeError:
                    # JSON이 아닐 경우 콤마로 분리
                    for t in tags_input.split(','):
                        if t.strip():
                            tag_obj, _ = Tag.objects.get_or_create(name=t.strip())
                            question.tags.add(tag_obj)

            # 3. 정답/보기 처리
            q_type = question.question_type

            # (A) 주관식: 정답이 여러 개(예: 사과, 과자)인 경우만 콤마로 구분
            # Apple/apple 같은 대소문자는 채점할 때 처리하므로 하나만 입력해도 됨.
            if q_type == 'short_answer':
                answer_text = request.POST.get('correct_answer_text', '')
                if answer_text:
                    # 콤마로 쪼개서 각각 정답으로 저장 (예: "사과, 배" -> 정답 2개 생성)
                    answers = [a.strip() for a in answer_text.split(',') if a.strip()]
                    for ans in answers:
                        Choice.objects.create(question=question, choice_text=ans, is_correct=True)

            # (B) 객관식 (단일/복수)
            elif q_type in ['multiple_choice', 'multiple_select']:
                for i in range(1, 5):
                    c_text = request.POST.get(f'choice_text_{i}', '').strip()
                    c_img = request.FILES.get(f'choice_image_{i}')
                    # 체크박스 값 확인 ('on'이면 True)
                    is_corr = request.POST.get(f'is_correct_{i}') == 'on'

                    if c_text or c_img:
                        Choice.objects.create(
                            question=question, choice_text=c_text, image=c_img, is_correct=is_corr
                        )

            # (C) OX
            elif q_type == 'true_false':
                ox_val = request.POST.get('ox_answer')
                Choice.objects.create(question=question, choice_text='O', is_correct=(ox_val == 'O'))
                Choice.objects.create(question=question, choice_text='X', is_correct=(ox_val == 'X'))

            messages.success(request, "새 문제가 등록되었습니다.")
            return redirect('quiz:question_list', quiz_id=quiz.id)

        except Exception as e:
            messages.error(request, f"오류 발생: {e}")
    
    # 태그 검색용 리스트
    all_tags_list = list(Tag.objects.values_list('name', flat=True))

    return render(request, 'quiz/manager/question_form.html', {'quiz': quiz})


# ------------------------------------------------------------------
# 문제 수정 (Update)
# ------------------------------------------------------------------
@login_required
def question_update(request, question_id):
    if not request.user.is_staff: 
        return redirect('quiz:index')
    
    question = get_object_or_404(Question, pk=question_id)
    related_quiz = question.quizzes.first()

    if request.method == 'POST':
        try:
            # 1. 정보 업데이트
            question.question_text = request.POST.get('question_text')
            question.question_type = request.POST.get('question_type')
            question.difficulty = request.POST.get('difficulty')
            
            if request.FILES.get('question_image'):
                question.image = request.FILES['question_image']
            
            question.save()

            # 2. [변경] 태그 업데이트 (Tagify JSON 처리)
            question.tags.clear()
            tags_json = request.POST.get('tags', '')
            if tags_json:
                try:
                    tag_list = json.loads(tags_json)
                    for tag_item in tag_list:
                        t_name = tag_item.get('value', '').strip()
                        if t_name:
                            tag_obj, _ = Tag.objects.get_or_create(name=t_name)
                            question.tags.add(tag_obj)
                except json.JSONDecodeError:
                    for t in tags_json.split(','):
                        if t.strip():
                            tag_obj, _ = Tag.objects.get_or_create(name=t.strip())
                            question.tags.add(tag_obj)

            # 3. 보기/정답 초기화 및 재생성
            question.choice_set.all().delete() 
            q_type = question.question_type

            # (A) [변경] 주관식 (복수 정답 허용)
            if q_type == 'short_answer':
                answer_text = request.POST.get('correct_answer_text', '')
                if answer_text:
                    answers = [a.strip() for a in answer_text.split(',') if a.strip()]
                    for ans in answers:
                        Choice.objects.create(question=question, choice_text=ans, is_correct=True)

            # (B) 객관식
            elif q_type in ['multiple_choice', 'multiple_select']:
                for i in range(1, 5):
                    c_text = request.POST.get(f'choice_text_{i}', '').strip()
                    c_img = request.FILES.get(f'choice_image_{i}')
                    is_corr = request.POST.get(f'is_correct_{i}') == 'on'

                    if c_text or c_img:
                        Choice.objects.create(
                            question=question, choice_text=c_text, image=c_img, is_correct=is_corr
                        )

            # (C) OX
            elif q_type == 'true_false':
                ox_val = request.POST.get('ox_answer')
                Choice.objects.create(question=question, choice_text='O', is_correct=(ox_val == 'O'))
                Choice.objects.create(question=question, choice_text='X', is_correct=(ox_val == 'X'))

            messages.success(request, "문제가 수정되었습니다.")
            
            if related_quiz:
                return redirect('quiz:question_list', quiz_id=related_quiz.id)
            else:
                return redirect('quiz:manager_quiz_list')

        except Exception as e:
            messages.error(request, f"수정 중 오류 발생: {e}")

    # GET 요청 처리
    # [변경] Tagify 초기값을 위해 콤마로 구분된 문자열 생성
    current_tags = ",".join(question.tags.values_list('name', flat=True))
    
    # [변경] 주관식 정답 가져오기 (여러 개일 경우 콤마로 합쳐서 보여줌)
    short_answer_val = ""
    if question.question_type == 'short_answer':
        correct_choices = question.choice_set.filter(is_correct=True).values_list('choice_text', flat=True)
        short_answer_val = ", ".join(correct_choices)
            
    ox_answer_val = ""
    if question.question_type == 'true_false':
        correct_choice = question.choice_set.filter(is_correct=True).first()
        if correct_choice:
            ox_answer_val = correct_choice.choice_text

    choices = question.choice_set.all()
    all_tags_list = list(Tag.objects.values_list('name', flat=True))

    return render(request, 'quiz/manager/question_form.html', {
        'question': question,
        'quiz': related_quiz,
        'title': '문제 수정',
        'current_tags': current_tags,
        'short_answer_val': short_answer_val,
        'ox_answer_val': ox_answer_val,
        'choices': question.choice_set.all(),
        'is_update': True,
        'all_tags_json': json.dumps(all_tags_list) # 전체 태그 리스트 (검색용)
    })


# ------------------------------------------------------------------
# 문제 삭제 (Delete) - 수정 사항 없음
# ------------------------------------------------------------------
@login_required
def question_delete(request, question_id):
    if not request.user.is_staff: return redirect('quiz:index')
    
    question = get_object_or_404(Question, pk=question_id)
    
    related_quiz = question.quizzes.first()
    quiz_id = related_quiz.id if related_quiz else None

    if request.method == 'POST':
        question.delete()
        messages.success(request, "문제가 삭제되었습니다.")
    
    if quiz_id:
        return redirect('quiz:question_list', quiz_id=quiz_id)
    return redirect('quiz:manager_quiz_list')

# ------------------------------------------------------------------
# 평가 (Evaluate Trainee) - [기존 유지]
# ------------------------------------------------------------------
@login_required
def evaluate_trainee(request, profile_id):
    # 1. 대상자 조회 및 권한 체크
    trainee = get_object_or_404(Profile, pk=profile_id)
    
    # [보안] 담당 매니저(교수) 또는 관리자만 평가 가능
    # (주의: is_process_manager 함수가 views.py 내 또는 utils에 정의되어 있어야 함)
    # if not is_process_manager(request.user, trainee):
    #     messages.error(request, "🚫 담당 공정의 매니저만 평가서를 작성할 수 있습니다.")
    #     return redirect('quiz:dashboard')

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
                
                # 최종 점수 재계산
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

# ------------------------------------------------------------------
# 시험 제출 처리 (Submit)
# ------------------------------------------------------------------
@login_required
def exam_submit(request, quiz_id):
    if request.method != 'POST':
        return redirect('quiz:take_quiz', quiz_id=quiz_id)

    quiz = get_object_or_404(Quiz, pk=quiz_id)
    
    # 1. 결과지(Result) 생성 (점수는 나중에 계산)
    result = QuizResult.objects.create(
        student=request.user,
        quiz=quiz,
        score=0, # 일단 0점
        submitted_at=timezone.now()
    )

    score = 0
    total_score = 0

    # 2. 문제별 정답 확인
    for question in quiz.questions.all():
        total_score += question.score # 총점 누적
        
        # 사용자가 선택/입력한 값 가져오기
        user_input = request.POST.get(f'question_{question.id}') # HTML의 input name과 일치
        
        is_correct = False
        
        # (A) 객관식/OX 처리
        if question.question_type in ['multiple_choice', 'true_false']:
            if user_input:
                # user_input은 choice의 ID(객관식) 또는 'O'/'X'(OX)일 수 있음
                # 로직에 따라 비교 (여기서는 ID 비교 예시)
                try:
                    selected_choice = Choice.objects.get(pk=user_input)
                    if selected_choice.is_correct:
                        is_correct = True
                except:
                    pass # OX인 경우 값 자체('O'/'X')로 비교 로직 필요

        # (B) 주관식 처리
        elif question.question_type == 'short_answer':
            if user_input:
                # 정답들과 비교 (대소문자 무시)
                correct_answers = question.choice_set.filter(is_correct=True).values_list('choice_text', flat=True)
                for ans in correct_answers:
                    if ans.strip().lower() == user_input.strip().lower():
                        is_correct = True
                        break

        # 3. 점수 합산 및 답안 저장
        if is_correct:
            score += question.score
        
        # 학생 답안 DB 저장 (선택 사항)
        StudentAnswer.objects.create(
            result=result,
            question=question,
            answer_text=user_input,
            is_correct=is_correct
        )

    # 4. 최종 점수 업데이트
    result.score = score
    result.save()

    # 결과 페이지로 이동 (urls.py에 exam_result가 있어야 함)
    return redirect('quiz:exam_result', result_id=result.id)

@login_required
def exam_result(request, result_id):
    # 본인 결과만 조회 가능
    result = get_object_or_404(QuizResult, pk=result_id, student=request.user)
    
    # 1. 이미 확인한 결과인지 체크 (새로고침/뒤로가기/재진입 차단)
    if result.is_viewed:
        messages.warning(request, "이미 확인한 시험 결과입니다. 다시 조회할 수 없습니다.")
        return redirect('quiz:index') # 목록으로 강제 이동

    # 2. 처음 보는 것이라면 '확인함'으로 상태 변경
    result.is_viewed = True
    result.save()

    # 답안 가져오기
    answers = result.studentanswer_set.select_related('question').all()
    
    context = {
        'result': result,
        'answers': answers,
        'quiz': result.quiz,
    }
    return render(request, 'quiz/exam_result.html', context)

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
    if not request.user.is_staff: return redirect('quiz:index')
    profile = get_object_or_404(Profile, pk=profile_id)
    logs = profile.logs.all()

    if request.method == 'POST':
        form = StudentLogForm(request.POST)
        if form.is_valid():
            log = form.save(commit=False)
            log.profile = profile
            log.created_by = request.user  # <--- recorder 아님! created_by로 수정
            
            # [A] 일반 경고 (누적 로직)
            if log.log_type == 'warning':
                profile.warning_count += 1
                log.save()
                
                # 2회: 1차 경고장 (자동) -> 잠금
                if profile.warning_count == 2:
                    StudentLog.objects.create(
                        profile=profile, recorder=request.user, log_type='warning_letter', 
                        reason="[시스템 자동] 일반 경고 2회 누적 -> 1차 경고장 발부",
                        action_taken="계정 잠금 (매니저 면담 필요)"
                    )
                    profile.status = 'counseling'
                    messages.warning(request, "⚠️ 경고 2회 누적! 1차 경고장이 발부되고 계정이 잠겼습니다.")

                # 3회: 2차 경고장 (자동) -> 잠금 (PL 면담 필수)
                elif profile.warning_count == 3:
                    StudentLog.objects.create(
                        profile=profile, recorder=request.user, log_type='warning_letter', 
                        reason="[시스템 자동] 일반 경고 3회 누적 -> 2차 경고장 발부",
                        action_taken="계정 잠금 (PL 면담 필수)"
                    )
                    profile.status = 'counseling'
                    messages.error(request, "🚫 경고 3회 누적! 2차 경고장이 발부되었습니다. (PL 면담 필수)")

                # 4회 이상: 퇴소
                elif profile.warning_count >= 4:
                    profile.status = 'dropout'
                    messages.error(request, "⛔ 경고 4회 누적! 퇴소 처리되었습니다.")
                
                # 1회: 주의
                else:
                    profile.status = 'caution'
                    messages.info(request, "일반 경고가 등록되었습니다. (상태: 주의)")

            # [B] 경고장 즉시 발부 (중대 과실)
            elif log.log_type == 'warning_letter':
                # 기존 0회였다면 2회(1차)로 점프, 이미 2회면 3회로 점프
                if profile.warning_count < 2: profile.warning_count = 2
                else: profile.warning_count += 1
                
                profile.status = 'counseling'
                if profile.warning_count >= 4: profile.status = 'dropout'
                
                log.save()
                messages.warning(request, f"⛔ 경고장이 즉시 발부되었습니다. (현재 누적: {profile.warning_count}회)")

            # [C] 면담 및 조치 (잠금 해제)
            elif log.log_type == 'counseling':
                is_resolve = request.POST.get('resolve_lock') == 'on'
                
                # 3회차(2차 경고장) 해제 시 PL 면담 확인 여부 (HTML에서 체크박스로 받을 예정)
                pl_check = request.POST.get('pl_check') == 'on'
                
                if is_resolve:
                    # 3회차인데 PL 면담 체크 안했으면 거부
                    if profile.warning_count == 3 and not pl_check:
                         messages.error(request, "🚫 3회 누적자는 'PL 면담 확인'을 체크해야 잠금이 해제됩니다.")
                         log.is_resolved = False
                         log.save()
                         return redirect('quiz:manage_student_logs', profile_id=profile.id)

                    log.is_resolved = True
                    # 퇴소 상태는 해제 불가
                    if profile.warning_count >= 4:
                        profile.status = 'dropout'
                        messages.warning(request, "퇴소 대상자는 잠금을 해제할 수 없습니다.")
                    else:
                        profile.status = 'attending'
                        messages.success(request, "✅ 조치가 완료되어 계정이 정상화되었습니다.")
                
                log.save()

            else:
                # 칭찬 등 기타
                log.save()
                messages.success(request, "기록되었습니다.")

            profile.save()
            return redirect('quiz:manage_student_logs', profile_id=profile.id)
    else:
        form = StudentLogForm()

    return render(request, 'quiz/manager/manage_student_logs.html', {
        'profile': profile, 'logs': logs, 'form': form
    })


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


@login_required
@require_POST
def manager_create_counseling_log(request, profile_id):
    """
    매니저가 시험 결과표에서 [면담] 버튼을 눌러 바로 기록을 남길 때 사용하는 함수
    """
    if not request.user.is_staff:
        return JsonResponse({'status': 'error', 'message': '권한이 없습니다.'}, status=403)

    try:
        profile = get_object_or_404(Profile, pk=profile_id)
        
        # 폼 데이터 받기
        content = request.POST.get('content')
        opinion = request.POST.get('opinion')
        is_passed = request.POST.get('is_passed') == 'on' # 체크박스 (잠금 해제용)

        if not content:
            return JsonResponse({'status': 'error', 'message': '면담 내용을 입력해주세요.'}, status=400)

        # 로그 저장 (StudentLog 사용)
        log = StudentLog.objects.create(
            profile=profile,
            created_by=request.user,  # <--- 여기 수정됨
            log_type='counseling',
            reason=content, 
            action_taken=opinion, 
            is_resolved=is_passed 
        )

        # 잠금 해제 로직 (체크 시)
        if is_passed and profile.status == 'counseling':
            profile.status = 'attending'
            profile.save()
            msg = "면담 기록 저장 및 잠금 해제 완료"
        else:
            msg = "면담 기록이 저장되었습니다."

        return JsonResponse({'status': 'success', 'message': msg})

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    
@login_required
def student_log_detail(request, log_id):
    """
    교육생이 자신의 특이사항/경고/평가 로그의 상세 내용을 확인하는 뷰
    """
    # 본인의 로그인지 확인 (보안)
    log = get_object_or_404(StudentLog, pk=log_id, profile=request.user.profile)
    
    return render(request, 'quiz/student_log_detail.html', {'log': log})

@login_required
def quiz_question_manager(request, quiz_id):
    """
    [좌측: 내 시험지] vs [우측: 전체 문제 은행] (필터링 기능 강화 + 시험 제목 필터)
    """
    if not request.user.is_staff: return redirect('quiz:index')
    
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    
    # 1. 현재 시험에 담긴 문제들
    added_questions = quiz.questions.all().order_by('-created_at')
    
    # 2. 문제 은행 (전체 문제 - 이미 담긴 문제 제외)
    bank_questions = Question.objects.exclude(id__in=added_questions.values_list('id', flat=True)).order_by('-created_at')

    # --- [검색 및 필터링 적용] ---
    search_query = request.GET.get('q', '')
    filter_tag = request.GET.get('tag', '')
    filter_difficulty = request.GET.get('difficulty', '')
    filter_quiz = request.GET.get('quiz_filter', '') # [신규] 시험 제목 필터

    # (A) 검색어 필터 (내용)
    if search_query:
        bank_questions = bank_questions.filter(question_text__icontains=search_query)
    
    # (B) 태그 필터 (공정 등)
    if filter_tag:
        bank_questions = bank_questions.filter(tags__id=filter_tag)
        
    # (C) 난이도 필터
    if filter_difficulty:
        bank_questions = bank_questions.filter(difficulty=filter_difficulty)
        
    # (D) [신규] 특정 시험에 포함된 문제만 보기
    if filter_quiz:
        bank_questions = bank_questions.filter(quizzes__id=filter_quiz)

    bank_questions = bank_questions.distinct()

    # 페이지네이션 (문제 은행만)
    paginator = Paginator(bank_questions, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    # 필터용 데이터
    all_tags = Tag.objects.all().order_by('name')
    difficulty_choices = Question.Difficulty.choices
    
    # [신규] 필터링용 시험 목록 (현재 시험 제외)
    all_quizzes_for_filter = Quiz.objects.exclude(id=quiz_id).order_by('title')

    return render(request, 'quiz/manager/quiz_question_manager.html', {
        'quiz': quiz,
        'added_questions': added_questions,
        'bank_questions': page_obj,
        
        # 필터링 상태 유지
        'search_query': search_query,
        'filter_tag': int(filter_tag) if filter_tag else '',
        'filter_difficulty': filter_difficulty,
        'filter_quiz': int(filter_quiz) if filter_quiz else '',
        
        # 드롭다운 메뉴용 데이터
        'all_tags': all_tags,
        'difficulty_choices': difficulty_choices,
        'all_quizzes_for_filter': all_quizzes_for_filter, # 추가됨
    })

@login_required
@require_POST
def add_question_to_quiz(request):
    """AJAX: 문제 은행에서 -> 내 시험지로 담기"""
    if not request.user.is_staff: return JsonResponse({'status':'error'}, status=403)
    try:
        data = json.loads(request.body)
        quiz = get_object_or_404(Quiz, pk=data.get('quiz_id'))
        questions = Question.objects.filter(id__in=data.get('question_ids', []))
        quiz.questions.add(*questions) # M2M 추가
        return JsonResponse({'status': 'success', 'count': questions.count()})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})

@login_required
@require_POST
def remove_question_from_quiz(request):
    """AJAX: 내 시험지에서 -> 문제 빼기 (삭제 아님, 관계만 끊기)"""
    if not request.user.is_staff: return JsonResponse({'status':'error'}, status=403)
    try:
        data = json.loads(request.body)
        quiz = get_object_or_404(Quiz, pk=data.get('quiz_id'))
        questions = Question.objects.filter(id__in=data.get('question_ids', []))
        quiz.questions.remove(*questions) # M2M 제거
        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})
    
@login_required
def my_notifications(request):
    """
    교육생 전용 알림/피드백 전체 목록 페이지
    """
    profile = request.user.profile
    
    # 필터링
    filter_type = request.GET.get('type', '')
    
    logs = StudentLog.objects.filter(profile=profile).order_by('-created_at')
    
    if filter_type:
        logs = logs.filter(log_type=filter_type)
        
    # 페이지네이션 (10개씩)
    paginator = Paginator(logs, 10)
    page_obj = paginator.get_page(request.GET.get('page'))
    
    # 읽지 않은 알림 개수 (예시 로직)
    # unread_count = logs.filter(is_read=False).count() 

    return render(request, 'quiz/my_notifications.html', {
        'page_obj': page_obj,
        'filter_type': filter_type,
        'log_types': StudentLog.LOG_TYPES,
    })

@login_required
def admin_full_data_view(request):
    """
    [관리자 전용] 엑셀 스타일의 마스터 그리드 뷰 (석차 계산 로직 추가)
    """
    if not request.user.is_superuser:
        messages.error(request, "접근 권한이 없습니다.")
        return redirect('quiz:dashboard')

    # 1. 파라미터 수신
    filter_cohort = request.GET.get('cohort', '')
    filter_process = request.GET.get('process', '')
    filter_company = request.GET.get('company', '')
    search_query = request.GET.get('q', '')
    start_date = request.GET.get('start_date', '')
    end_date = request.GET.get('end_date', '')

    # 2. [석차 계산] 전체 인원에 대한 랭킹 미리 계산 (필터링 전 데이터 기준)
    # (FinalAssessment가 있는 인원만 대상)
    all_assessments = FinalAssessment.objects.filter(
        final_score__isnull=False
    ).select_related('profile').values(
        'profile__id', 'final_score', 
        'profile__cohort_id', 'profile__process_id', 'profile__company_id'
    )

    # 딕셔너리로 변환 및 정렬 (점수 내림차순)
    data_pool = list(all_assessments)
    data_pool.sort(key=lambda x: x['final_score'], reverse=True)

    # 석차 저장소 { profile_id: { 'overall': 1, 'cohort': 3, ... } }
    rank_map = defaultdict(dict)

    # (A) 전체 석차 계산
    curr_rank = 1
    for i, item in enumerate(data_pool):
        if i > 0 and item['final_score'] < data_pool[i-1]['final_score']:
            curr_rank = i + 1
        rank_map[item['profile__id']]['overall'] = curr_rank

    # (B) 그룹별 석차 계산 함수
    def calculate_group_rank(group_key, rank_name):
        grouped = defaultdict(list)
        for item in data_pool:
            grouped[item[group_key]].append(item)
        
        for g_id, items in grouped.items():
            # 이미 점수순 정렬되어 있음
            g_rank = 1
            for i, item in enumerate(items):
                if i > 0 and item['final_score'] < items[i-1]['final_score']:
                    g_rank = i + 1
                rank_map[item['profile__id']][rank_name] = g_rank

    calculate_group_rank('profile__cohort_id', 'cohort')   # 기수별
    calculate_group_rank('profile__process_id', 'process') # 공정별
    calculate_group_rank('profile__company_id', 'company') # 회사별


    # 3. 화면 표시용 프로필 조회 (필터링 적용)
    profiles = Profile.objects.select_related(
        'user', 'cohort', 'company', 'process', 'pl', 'final_assessment'
    ).prefetch_related(
        'user__testresult_set', 
        'user__testresult_set__quiz',
        'dailyschedule_set__work_type',
        'logs', 
        'managerevaluation_set__selected_items'
    ).order_by('cohort__start_date', 'user__username')

    # 필터 적용
    if filter_cohort: profiles = profiles.filter(cohort_id=filter_cohort)
    if filter_process: profiles = profiles.filter(process_id=filter_process)
    if filter_company: profiles = profiles.filter(company_id=filter_company)
    if start_date: profiles = profiles.filter(joined_at__gte=start_date)
    if end_date: profiles = profiles.filter(joined_at__lte=end_date)
    if search_query:
        profiles = profiles.filter(
            Q(name__icontains=search_query) | 
            Q(user__username__icontains=search_query) |
            Q(employee_id__icontains=search_query)
        )

    # 4. 데이터 가공
    all_quizzes = Quiz.objects.all().order_by('title')
    table_rows = []

    for p in profiles:
        # 퀴즈 점수
        user_results = p.user.testresult_set.all()
        result_map = defaultdict(list)
        for r in user_results:
            result_map[r.quiz.id].append(r)
        
        ordered_scores = [] 
        for quiz in all_quizzes:
            attempts = sorted(result_map[quiz.id], key=lambda x: x.completed_at)
            scores_pkg = []
            for i in range(3):
                if i < len(attempts):
                    scores_pkg.append({'val': attempts[i].score, 'is_pass': attempts[i].is_pass})
                else:
                    scores_pkg.append({'val': '-', 'is_pass': False})
            ordered_scores.append(scores_pkg)

        # 근태
        schedules = p.dailyschedule_set.all()
        w_cnt = schedules.filter(work_type__deduction=0).count()
        l_cnt = schedules.filter(work_type__deduction=1.0).count()
        h_cnt = schedules.filter(work_type__deduction=0.5).count()
        
        # 로그 및 평가
        logs_list = p.logs.all().order_by('-created_at')
        fa = getattr(p, 'final_assessment', None)
        last_eval = p.managerevaluation_set.last()
        manager_comment = last_eval.overall_comment if last_eval else ""

        # [석차 정보 가져오기]
        my_ranks = rank_map.get(p.id, {})

        table_rows.append({
            'profile': p,
            'ordered_scores': ordered_scores,
            'attendance': {'work': w_cnt, 'leave': l_cnt, 'half': h_cnt},
            'final': fa,
            'ranks': my_ranks, # 계산된 석차 딕셔너리 전달
            'logs': logs_list,
            'manager_comment': manager_comment,
            'log_count': logs_list.count()
        })

    context = {
        'table_rows': table_rows,
        'quizzes': all_quizzes,
        'total_count': profiles.count(),
        'cohorts': Cohort.objects.all(),
        'processes': Process.objects.all(),
        'companies': Company.objects.all(),
        'sel_cohort': int(filter_cohort) if filter_cohort else '',
        'sel_process': int(filter_process) if filter_process else '',
        'sel_company': int(filter_company) if filter_company else '',
        'sel_start': start_date,
        'sel_end': end_date,
        'sel_q': search_query,
    }

    return render(request, 'quiz/manager/admin_full_data.html', context)

@login_required
def student_log_create(request, student_id):
    # 1. 대상 학생(Profile) 찾기
    target_profile = get_object_or_404(Profile, pk=student_id)

    if request.method == 'POST':
        form = StudentLogForm(request.POST)
        if form.is_valid():
            log = form.save(commit=False)
            
            # [수정 완료] 모델 필드명(created_by)과 정확히 일치시킴
            log.profile = target_profile    
            log.created_by = request.user   # recorder (X) -> created_by (O)
            
            log.save()
            messages.success(request, "기록이 저장되었습니다.")
            return redirect(request.META.get('HTTP_REFERER', 'quiz:index'))
    
    return redirect(request.META.get('HTTP_REFERER', 'quiz:index'))

@login_required
def notification_list(request):
    """
    내게 온 알림 목록을 보여주는 페이지
    """
    # 내 알림만 가져오기 (최신순)
    notis = Notification.objects.filter(recipient=request.user).order_by('-created_at')
    
    # 읽지 않은 알림 개수
    unread_count = notis.filter(is_read=False).count()
    
    return render(request, 'quiz/notification_list.html', {
        'notifications': notis,
        'unread_count': unread_count
    })

# -----------------------------------------------------------
# [누락된 함수 2] 알림 읽음 처리 및 이동
# -----------------------------------------------------------
@login_required
def notification_read(request, noti_id):
    """
    알림을 클릭하면 '읽음' 처리하고 해당 링크로 이동
    """
    noti = get_object_or_404(Notification, pk=noti_id)
    
    # 본인 알림인지 확인 (남의 알림을 볼 수 없도록)
    if noti.recipient != request.user:
        messages.error(request, "권한이 없습니다.")
        return redirect('quiz:index')
        
    # 읽음 처리
    noti.is_read = True
    noti.save()
    
    # 연결된 주소(related_url)가 있으면 이동, 없으면 알림 목록으로 리다이렉트
    return redirect(noti.related_url if noti.related_url else 'quiz:notification_list')

@staff_member_required
def bulk_add_sheet_view(request):
    # 퀴즈 목록을 ID 역순으로 가져오기
    quizzes = Quiz.objects.all().order_by('-id') 
    return render(request, 'quiz/bulk_add_sheet.html', {'quizzes': quizzes})