# quiz/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import TestResult, Quiz
from accounts.models import Badge, Profile
from django.db.models import Avg

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