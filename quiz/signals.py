# quiz/signals.py

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db.models import Avg, Q
from django.contrib.auth import get_user_model
from django.urls import reverse
from quiz.views import broadcast_realtime_notification

# 모델 임포트 (기존 + 신규 통합)
from .models import TestResult, Quiz, Reservation, Notification, Room
from accounts.models import Badge, Profile

# ★ [중요] 아래 모델들은 실제 프로젝트에 있는 모델명으로 import 하세요! (주석 해제 시 필요)
# from .models import Consultation, ExamRequest, WorkSchedule 

User = get_user_model()

# =========================================================
# [Part 1] 뱃지 시스템 (기존 코드 유지)
# =========================================================

@receiver(post_save, sender=TestResult)
def award_badges_on_test_completion(sender, instance, created, **kwargs):
    """ 시험 결과가 생성될 때 뱃지 획득 조건을 확인합니다. """
    if not created:
        return

    user = instance.user
    profile, created_profile = Profile.objects.get_or_create(user=user)

    # 뱃지 획득 로직
    check_achievement_badges(profile, instance)
    check_special_badges(profile, instance)
    check_quirky_badges(profile, instance)
    check_meta_badges(profile)

def check_achievement_badges(profile, result):
    user = profile.user

    # 성취 1: 첫 100점 달성
    if result.score == 100:
        badge, created = Badge.objects.get_or_create(name="완벽한 시작", defaults={'description': "처음으로 100점을 달성했습니다."})
        profile.badges.add(badge)

    # 성취 2: 노력의 결실 (같은 시험 점수 30점 이상 상승)
    past_results = TestResult.objects.filter(user=user, quiz=result.quiz).order_by('completed_at')
    if past_results.count() > 1:
        first_score = past_results.first().score
        if result.score >= first_score + 30:
            badge, created = Badge.objects.get_or_create(name="노력의 결실", defaults={'description': "같은 시험의 첫 점수보다 30점 이상 점수를 올렸습니다."})
            profile.badges.add(badge)

    # 성취 3: 성실한 응시자 (총 응시 횟수 10회 돌파)
    if TestResult.objects.filter(user=user).count() >= 10:
        badge, created = Badge.objects.get_or_create(name="성실한 응시자", defaults={'description': "총 시험 응시 횟수 10회를 돌파했습니다."})
        profile.badges.add(badge)

    # 성취 4: 정복자 (모든 종류의 시험에 한 번 이상 응시)
    quizzes_taken_count = TestResult.objects.filter(user=user).values('quiz').distinct().count()
    if quizzes_taken_count == Quiz.objects.count():
        badge, created = Badge.objects.get_or_create(name="정복자", defaults={'description': "사이트의 모든 종류의 시험에 응시했습니다."})
        profile.badges.add(badge)

    # 성취 5: 지식의 대가 (전체 평균 90점 돌파)
    avg_score = TestResult.objects.filter(user=user).aggregate(Avg('score'))['score__avg']
    if avg_score and avg_score >= 90:
        badge, created = Badge.objects.get_or_create(name="지식의 대가", defaults={'description': "전체 시험 평균 90점을 돌파했습니다."})
        profile.badges.add(badge)


def check_special_badges(profile, result):
    user = profile.user

    # 특별 1: 첫걸음 (첫 시험 완료)
    if TestResult.objects.filter(user=user).count() == 1:
        badge, created = Badge.objects.get_or_create(name="첫걸음", defaults={'description': "첫 시험을 성공적으로 완료했습니다."})
        profile.badges.add(badge)

    # 특별 2: 협력자 (그룹 배정 시험 완료)
    if result.attempt and result.attempt.assignment_type == '그룹 배정':
        badge, created = Badge.objects.get_or_create(name="협력자", defaults={'description': "그룹 배정 시험을 완료했습니다."})
        profile.badges.add(badge)

    # 특별 3: 재도전자 (같은 시험 3회 이상 응시)
    if TestResult.objects.filter(user=user, quiz=result.quiz).count() >= 3:
        badge, created = Badge.objects.get_or_create(name="재도전자", defaults={'description': "같은 종류의 시험에 3회 이상 응시했습니다."})
        profile.badges.add(badge)


def check_quirky_badges(profile, result):
    # 엉뚱 1: 아슬아슬 (60~65점 사이 점수 획득)
    if 60 <= result.score <= 65:
        badge, created = Badge.objects.get_or_create(name="아슬아슬", defaults={'description': "60~65점 사이의 점수를 획득했습니다."})
        profile.badges.add(badge)

    # 엉뚱 2: 괜찮아, 다시 하면 돼 (30점 이하 점수 획득)
    if result.score <= 30:
        badge, created = Badge.objects.get_or_create(name="괜찮아, 다시 하면 돼", defaults={'description': "30점 이하의 점수를 획득했습니다. 다음엔 더 잘할 수 있어요!"})
        profile.badges.add(badge)

def check_meta_badges(profile):
    # 엉뚱 3 (메타 뱃지): 수집가 (뱃지 5개 이상 획득)
    if profile.badges.count() >= 5:
        badge, created = Badge.objects.get_or_create(name="수집가", defaults={'description': "5개 이상의 뱃지를 획득했습니다."})
        profile.badges.add(badge)


# =========================================================
# [Part 2] 알림 시스템 
# =========================================================

# 1. [시설 예약] 신청 시 -> 관리자에게 알림 (링크 포함)
@receiver(post_save, sender=Reservation)
def notify_facility_reservation(sender, instance, created, **kwargs):
    if created and instance.status == 'pending':
        # 슈퍼유저들에게 알림 발송
        admins = User.objects.filter(is_superuser=True)
        for admin in admins:
            Notification.objects.create(
                recipient=admin,
                sender=instance.user,
                message=f"🏢 {instance.user.first_name}님이 [{instance.room.name}] 예약을 신청했습니다.",
                notification_type='facility', 
                related_url='/quiz/manager/facility/',  # ★ 클릭 시 이동할 주소
                
            )

            broadcast_realtime_notification(admin.id)

# =========================================================
# [Part 3] 점수 자동 갱신 (★ 핵심 추가)
# =========================================================
@receiver(post_save, sender=TestResult)
def update_final_assessment_stats(sender, instance, created, **kwargs):
    """
    시험 결과가 나오면 -> FinalAssessment의 '시험 평균 점수'를 즉시 재계산
    (환경안전 및 타 공정 시험 제외 로직 포함)
    """
    try:
        user = instance.user
        if not hasattr(user, 'profile'):
            return

       # 1. 계산 대상이 되는 시험 결과들 1차 필터링
        base_results = TestResult.objects.filter(user=user) \
            .exclude(quiz__category__in=['safety', 'etc'])

        user_process = user.profile.process
        if user_process:
            base_results = base_results.filter(
                Q(quiz__related_process=user_process) | 
                Q(quiz__related_process__isnull=True)
            )

        # 2. 중복을 제거한 '퀴즈 종류(ID)' 추출
        target_quiz_ids = base_results.values_list('quiz_id', flat=True).distinct()

        total_first_score = 0
        quiz_count = 0

        # 3. 각 퀴즈별로 '가장 오래된(First) 기록'만 찾아서 합산
        for q_id in target_quiz_ids:
            first_attempt = TestResult.objects.filter(user=user, quiz_id=q_id).order_by('completed_at').first()
            
            if first_attempt:
                total_first_score += first_attempt.score
                quiz_count += 1

        # 4. 1차 점수 기준 평균 계산
        new_avg = round(total_first_score / quiz_count, 1) if quiz_count > 0 else 0 

        # 3. FinalAssessment 업데이트
        from accounts.models import FinalAssessment
        assessment, _ = FinalAssessment.objects.get_or_create(profile=user.profile)

        if assessment.exam_avg_score != new_avg:
            assessment.exam_avg_score = new_avg
            # 저장 시 accounts/models.py의 Signal이 발동하여 환산점수(85:5:10) 재계산됨
            assessment.save()
            
    except Exception as e:
        print(f"❌ [통계 갱신 오류] {e}")


# 2. [면담 요청] 발생 시 -> (추후 사용 시 주석 해제)
# @receiver(post_save, sender=Consultation) 
# def notify_consultation(sender, instance, created, **kwargs):
#     if created:
#         admins = User.objects.filter(is_superuser=True)
#         for admin in admins:
#             Notification.objects.create(
#                 recipient=admin,
#                 sender=instance.user,
#                 message=f"💬 {instance.user.first_name}님이 면담을 요청했습니다.",
#                 notification_type='consult',  # ★ 면담 아이콘 타입
#                 # ★ 중요: 실제 면담 상세 페이지 URL이나 목록 페이지 URL을 넣으세요.
#                 related_url=f'/quiz/manager/consultation/{instance.id}/' 
#             )

# 3. [시험 요청] 발생 시 -> (추후 사용 시 주석 해제)
# @receiver(post_save, sender=ExamRequest)
# def notify_exam_request(sender, instance, created, **kwargs):
#     if created:
#         admins = User.objects.filter(is_superuser=True)
#         for admin in admins:
#             Notification.objects.create(
#                 recipient=admin,
#                 sender=instance.user,
#                 message=f"📝 {instance.user.first_name}님이 시험 승인을 요청했습니다.",
#                 notification_type='exam',
#                 related_url='/quiz/manager/exam_requests/' # 승인 페이지 URL
#             )