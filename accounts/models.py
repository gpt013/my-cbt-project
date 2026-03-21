from django.db import models
from django.contrib.auth.models import User, Group, Permission 
from django.contrib.contenttypes.models import ContentType 
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from django.db.models import Avg, F, Window, Q
from django.db.models.functions import DenseRank
import random

# -----------------------------------------------------------
# 1. 기초 정보 모델 (기수, 회사, 공정, PL, 뱃지)
# -----------------------------------------------------------

class Cohort(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="기수 이름 (예: 25-01기)")
    start_date = models.DateField(verbose_name="교육 시작일")
    end_date = models.DateField(verbose_name="교육 종료일", null=True, blank=True)
    is_registration_open = models.BooleanField(
        default=True, 
        verbose_name="가입 활성화 여부",
        help_text="이 옵션을 체크해야 해당 기수 인원이 가입할 수 있습니다."
    )
    is_closed = models.BooleanField(default=False, verbose_name="평가 마감 완료")

    class Meta:
        verbose_name = "기수 (교육 차수)"
        verbose_name_plural = "기수 (교육 차수)"
        ordering = ['-start_date']

    def __str__(self):
        return f"{self.name} ({self.start_date})"

class Company(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="회사 이름")
    class Meta:
        verbose_name = "회사"
        verbose_name_plural = "회사"
    def __str__(self):
        return self.name

class Process(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="공정 이름")
    class Meta:
        verbose_name = "공정"
        verbose_name_plural = "공정"
    def __str__(self):
        return self.name

class PartLeader(models.Model):
    name = models.CharField(max_length=50, unique=True, verbose_name="PL 이름")
    email = models.EmailField(unique=True, verbose_name="PL 이메일", help_text="성적표 발송 및 알림용")
    company = models.ForeignKey('Company', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="소속 회사")
    process = models.ManyToManyField('Process', blank=True, verbose_name='담당 공정들')

    class Meta:
        verbose_name = "PL(파트장)"
        verbose_name_plural = "PL(파트장)"
        
    def __str__(self):
        return self.name

class Badge(models.Model):
    name = models.CharField(max_length=100, verbose_name="뱃지 이름")
    description = models.TextField(verbose_name="획득 조건 설명")
    image = models.ImageField(upload_to='badges/', blank=True, null=True, verbose_name="뱃지 이미지")
    class Meta:
        verbose_name = "뱃지"
        verbose_name_plural = "뱃지"
    def __str__(self):
        return self.name

class RecordType(models.Model):
    name = models.CharField(max_length=50, unique=True, verbose_name="기록 유형 이름")
    class Meta:
        verbose_name = "평가 기록 유형"
        verbose_name_plural = "평가 기록 유형"
    def __str__(self):
        return self.name


# -----------------------------------------------------------
# 2. 핵심 사용자 정보 (Profile) - [수정됨]
# -----------------------------------------------------------

class Profile(models.Model):
    # [상태 정의]
    STATUS_CHOICES = [
        ('attending', '재직 (정상)'),
        ('caution', '주의 (경고 1회)'),      
        ('counseling', '면담필요 (잠금)'),  
        ('dropout', '미수료 및 퇴소'), # ✅ 두 가지 케이스를 모두 포함하는 이름으로 변경
        ('completed', '수료 (과정완료)'),
    ]

    # related_name='profile'을 추가해 user.profile 로 쉽게 접근하도록 함
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    
    # 기본 정보
    company = models.ForeignKey('Company', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="소속 회사")
    name = models.CharField(max_length=50, verbose_name='이름', blank=True, null=True)
    employee_id = models.CharField(max_length=50, verbose_name='사번', blank=True, null=True)
    cohort = models.ForeignKey('Cohort', on_delete=models.SET_NULL, null=True, blank=False, verbose_name="소속 기수")
    process = models.ForeignKey('Process', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="공정")
    line = models.CharField(max_length=100, verbose_name='라인', blank=True, null=True)
    pl = models.ForeignKey('PartLeader', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="담당 PL")

    # [신규] 입사일 (연차 계산용)
    joined_at = models.DateField(null=True, blank=True, verbose_name="입사일(교육시작일)", help_text="연차 계산 기준일입니다.")

    # [기능성 필드]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='attending', verbose_name="현재 상태")
    
    # [신규] 누적 경고 카운터 (경고장 발부 기준)
    warning_count = models.IntegerField(default=0, verbose_name="누적 경고 횟수")
    
    is_manager = models.BooleanField(default=False, verbose_name="매니저 권한 여부")
    is_pl = models.BooleanField(default=False, verbose_name="PL 권한 여부") 
    
    # ★ [필수 추가] 관리자 승인 여부 (인트라넷 가입 시 필수)
    is_approved = models.BooleanField(default=False, verbose_name="관리자 승인 여부")

    # 프로필 작성 완료 여부 (2차 정보 기입 확인용)
    is_profile_complete = models.BooleanField(default=False, verbose_name="프로필 작성 완료")
    
    must_change_password = models.BooleanField(default=False, verbose_name="비밀번호 변경 필요")
    
    badges = models.ManyToManyField('Badge', blank=True, verbose_name="획득한 뱃지")

    session_key = models.CharField(max_length=40, null=True, blank=True, verbose_name="현재 세션 키")
    
    def __str__(self):
        return f"{self.name} ({self.get_status_display()})"



# -----------------------------------------------------------
# 3. 평가 및 데이터 관리 모델 (종합 평가, 요청 등)
# -----------------------------------------------------------

# [신규] 이메일 인증 코드 저장
class EmailVerification(models.Model):
    email = models.EmailField(unique=True, verbose_name="이메일")
    code = models.CharField(max_length=6, verbose_name="인증 코드")
    created_at = models.DateTimeField(auto_now_add=True)
    is_verified = models.BooleanField(default=False, verbose_name="인증 완료 여부")

    def is_expired(self):
        # 5분 유효시간
        return (timezone.now() - self.created_at).total_seconds() > 300

# [신규] 종합 평가 (성적표/생기부용 데이터)
class FinalAssessment(models.Model):
    profile = models.OneToOneField(Profile, on_delete=models.CASCADE, related_name='final_assessment', verbose_name="대상 교육생")
    
    # 점수 입력란
    exam_avg_score = models.FloatField(default=0, verbose_name="시험 평균(자동)")
    practice_score = models.FloatField(default=0, verbose_name="실습 점수")
    note_score = models.FloatField(default=0, verbose_name="노트 점수")
    attitude_score = models.FloatField(default=0, verbose_name="인성/태도 점수")
    
    final_score = models.FloatField(default=0, verbose_name="최종 환산 점수")
    rank = models.PositiveIntegerField(default=0, verbose_name="기수 내 등수", null=True, blank=True)
    
    manager_comment = models.TextField(verbose_name="최종 코멘트", blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "최종 종합 평가"
        verbose_name_plural = "최종 종합 평가"

    def calculate_final_score(self):
        self.final_score = (
            (self.exam_avg_score * 0.85) + 
            (self.practice_score * 0.05) + 
            (self.attitude_score * 0.10)
        )
        self.save()



# (기존) 일반 평가 기록
class EvaluationRecord(models.Model):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, verbose_name="프로필")
    record_type = models.ForeignKey(RecordType, on_delete=models.SET_NULL, null=True, verbose_name="기록 유형")
    description = models.TextField(verbose_name="세부 내용")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "수시 평가 기록"
        verbose_name_plural = "수시 평가 기록"
        ordering = ['-created_at']

# (기존) 매니저 평가 시스템 (체크리스트)
class EvaluationCategory(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="평가 항목")
    order = models.PositiveIntegerField(default=0, verbose_name="표시 순서")
    
    class Meta:
        verbose_name = "평가 항목 (대분류)"         # [수정] 한글 이름
        verbose_name_plural = "평가 항목 (대분류)"  # [수정] 한글 이름 (복수형)
        ordering = ['order']

    def __str__(self):
        return self.name

class EvaluationItem(models.Model):
    category = models.ForeignKey(EvaluationCategory, on_delete=models.CASCADE, verbose_name="평가 항목")
    description = models.CharField(max_length=255, verbose_name="평가 예시 (체크할 내용)")
    is_positive = models.BooleanField(default=True, verbose_name="긍정/부정 (장점/단점)")

    class Meta:
        verbose_name = "평가 세부 항목 (체크리스트)"        # [수정] 한글 이름
        verbose_name_plural = "평가 세부 항목 (체크리스트)" # [수정] 한글 이름
        ordering = ['category__order', 'id']

    def __str__(self):
        return f"[{self.category.name}] {self.description}"

class ManagerEvaluation(models.Model):
    trainee_profile = models.ForeignKey(Profile, on_delete=models.CASCADE)
    manager = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    selected_items = models.ManyToManyField(EvaluationItem, blank=True)
    overall_comment = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "매니저 최종 평가서"
        verbose_name_plural = "매니저 최종 평가서"
        ordering = ['-created_at']

    def __str__(self):
        manager_name = self.manager.username if self.manager else "알 수 없음"
        return f"{self.trainee_profile.name} 평가 ({manager_name})"

# (기존) 권한 요청 티켓
class ProcessAccessRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', '대기중'),
        ('approved', '승인됨 (미사용)'),
        ('expired', '사용완료 (만료)'),
        ('rejected', '거절됨'),
    ]
    requester = models.ForeignKey(User, on_delete=models.CASCADE, related_name='access_requests')
    target_process = models.ForeignKey(Process, on_delete=models.CASCADE, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        target_name = self.target_process.name if self.target_process else "🌍 전체 공정"
        return f"{self.requester.profile.name} -> {target_name} ({self.status})"

# -----------------------------------------------------------
# 4. Signals (자동화 로직)
# -----------------------------------------------------------

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    # [핵심 수정] 무한 루프 방지: 여기서 profile.save()를 호출하면 안 됩니다!
    # Profile이 없는 경우에만 생성하고, 저장은 하지 않습니다.
    if not hasattr(instance, 'profile'):
        Profile.objects.create(user=instance)
    # instance.profile.save()  <-- 이 줄을 삭제하여 덮어쓰기 방지

@receiver(post_save, sender=Profile)
def manage_permissions(sender, instance, created, **kwargs):
    user = instance.user
    
    manager_group, group_created = Group.objects.get_or_create(name='매니저')

    # (그룹 권한 부여 로직은 위와 동일 - 생략 없이 포함됨)
    if group_created:
        from quiz.models import Quiz, Question, Choice, ExamSheet, Tag, QuizAttempt, TestResult
        
        full_access_models = [Quiz, Question, Choice, ExamSheet, Tag, PartLeader, ManagerEvaluation, EvaluationRecord, FinalAssessment, ]
        for model in full_access_models:
            ct = ContentType.objects.get_for_model(model)
            perms = Permission.objects.filter(content_type=ct)
            manager_group.permissions.add(*perms)

        result_models = [TestResult, QuizAttempt]
        for model in result_models:
            ct = ContentType.objects.get_for_model(model)
            perms = Permission.objects.filter(content_type=ct)
            manager_group.permissions.add(*perms)

        ct_profile = ContentType.objects.get_for_model(Profile)
        perms_profile = Permission.objects.filter(content_type=ct_profile, codename__in=['change_profile', 'view_profile'])
        manager_group.permissions.add(*perms_profile)

        ct_user = ContentType.objects.get_for_model(User)
        perms_user = Permission.objects.filter(content_type=ct_user, codename='view_user')
        manager_group.permissions.add(*perms_user)
        manager_group.save()

    # [권한 부여/해제]
    if instance.is_manager:
        if not user.is_staff:
            user.is_staff = True
            user.save() # 여기서 User save -> save_user_profile 호출되지만, 거기서 profile.save()를 뺐으므로 루프 안 생김
        if not user.groups.filter(name='매니저').exists():
            user.groups.add(manager_group)
    else:
        if not user.is_superuser:
            if not instance.is_pl and user.is_staff:
                user.is_staff = False
                user.save()
            if user.groups.filter(name='매니저').exists():
                user.groups.remove(manager_group)


@receiver(post_save, sender=FinalAssessment)
def update_score_and_rank(sender, instance, created, **kwargs):
    # 1. 무한 루프 및 중복 실행 방지
    if getattr(instance, '_processing', False):
        return
    
    from quiz.models import TestResult, Quiz

    # ---------------------------------------------------------
    # [1단계] 시험 평균 점수 최신화 (1차 점수만 반영)
    # ---------------------------------------------------------
    user = instance.profile.user
    user_process = instance.profile.process

    # 1. 계산 대상이 되는 시험 결과들 1차 필터링
    # (안전/기타 제외)
    base_results = TestResult.objects.filter(user=user) \
        .exclude(quiz__category__in=['safety', 'etc'])

    # (내 공정 or 공통 과목만 포함)
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
    current_exam_avg = round(total_first_score / quiz_count, 1) if quiz_count > 0 else 0

    
    
    # ---------------------------------------------------------
    # [2단계] 점수 변동 체크 및 반영
    # ---------------------------------------------------------
    need_save = False
    
    # 시험 점수가 바뀌었으면 업데이트
    if instance.exam_avg_score != current_exam_avg:
        instance.exam_avg_score = current_exam_avg
        need_save = True

    # ★ [핵심] 환산 점수 공식 적용 (시험85 + 실습5 + 태도10)
    new_final_score = (
        (instance.exam_avg_score * 0.85) + 
        (instance.practice_score * 0.05) + 
        (instance.attitude_score * 0.10)
    )
    
    # 소수점 2자리 반올림
    new_final_score = round(new_final_score, 2)

    if instance.final_score != new_final_score:
        instance.final_score = new_final_score
        need_save = True

    # ---------------------------------------------------------
    # [3단계] 저장 (변경된 경우에만 수행)
    # ---------------------------------------------------------
    if need_save:
        instance._processing = True # 락 걸기
        instance.save()
        instance._processing = False

    # ---------------------------------------------------------
    # [4단계] 기수 전체 랭킹 재산정 (최적화: bulk_update 사용)
    # ---------------------------------------------------------
    # 해당 기수의 모든 평가서를 점수 높은 순으로 가져옴
    cohort_assessments = FinalAssessment.objects.filter(
        profile__cohort=instance.profile.cohort
    ).order_by('-final_score')

    update_list = []
    current_rank = 1
    prev_score = -1
    
    for i, assessment in enumerate(cohort_assessments):
        if i == 0:
            assessment.rank = 1
            prev_score = assessment.final_score
        else:
            # 동점자 처리 (점수가 같으면 같은 등수)
            if assessment.final_score < prev_score:
                current_rank += 1
            assessment.rank = current_rank
            prev_score = assessment.final_score
        
        update_list.append(assessment)

    # ★ 중요: 한 번에 업데이트 (Signal을 다시 트리거하지 않아 안전함)
    if update_list:
        FinalAssessment.objects.bulk_update(update_list, ['rank'])

class DropOutRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', '승인 대기'),
        ('approved', '승인 완료'),
        ('rejected', '반려됨'),
    ]

    trainee = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name='dropout_records', verbose_name="대상 교육생")
    requester = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name="요청 매니저")
    
    drop_date = models.DateField(verbose_name="퇴사/퇴소(예정)일")
    reason = models.TextField(verbose_name="퇴사/퇴소 사유")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name="결재 상태")
    
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True, verbose_name="결재 처리일시")

    class Meta:
        verbose_name = "중도 퇴사 요청"
        verbose_name_plural = "중도 퇴사 요청 관리"

    def __str__(self):
        return f"[{self.get_status_display()}] {self.trainee.name} 퇴사 요청"

@receiver(post_save, sender=DropOutRequest)
def process_dropout_approval(sender, instance, **kwargs):
    """
    최고 관리자가 중도 퇴사 요청을 승인하면, 학생 상태를 변경하고
    요청한 매니저에게 즉시 알림을 발송합니다.
    """
    if instance.status == 'approved' and instance.trainee.status != 'dropout':
        trainee_profile = instance.trainee
        trainee_profile.status = 'dropout'
        trainee_profile.save()

        try:
            from quiz.models import Notification
            if instance.requester:
                Notification.objects.create(
                    recipient=instance.requester,
                    notification_type='general',
                    message=f"📢 [{trainee_profile.name}] 교육생의 중도 퇴사가 승인되었습니다. 최종 평가서를 마감해 주세요.",
                    related_url=f"/quiz/manager/evaluate/{trainee_profile.id}/"
                )
        except Exception as e:
            print(f"알림 발송 오류: {e}")


@receiver(post_save, sender=Profile)
def check_cohort_completion(sender, instance, **kwargs):
    """
    학생의 상태(수료, 퇴소 등)가 변경될 때마다 해당 기수의 마감 여부를 검사합니다.
    """
    cohort = instance.cohort
    # 매니저, PL이 아니며, 소속 기수가 있고, 아직 마감되지 않은 기수일 때만 검사
    if not cohort or instance.is_manager or instance.is_pl or cohort.is_closed:
        return

    # 1. 해당 기수의 전체 유효 학생 수 (매니저/PL 제외, 승인된 인원)
    total_students = Profile.objects.filter(
        cohort=cohort, is_manager=False, is_pl=False, is_approved=True
    ).count()

    # 2. 평가가 완전히 끝난 인원 (수료자 + 퇴소자)
    finished_students = Profile.objects.filter(
        cohort=cohort, is_manager=False, is_pl=False, is_approved=True,
        status__in=['completed', 'dropout']
    ).count()

    # 3. 전원 평가 완료 감지!
    if total_students > 0 and total_students == finished_students:
        # 기수 마감 처리 (중복 알림 방지)
        cohort.is_closed = True
        cohort.save()

        # 4. 모든 매니저와 관리자에게 축하/확인 알림 발송
        managers = User.objects.filter(Q(profile__is_manager=True) | Q(is_superuser=True)).distinct()
        
        # [주의] Notification 모델이 있는 앱(quiz 또는 다른 앱)에서 임포트해야 합니다.
        from quiz.models import Notification 
        
        for manager in managers:
            Notification.objects.create(
                recipient=manager,
                notification_type='general',
                message=f"🎉 [{cohort.name}] 기수의 모든 평가(수료/퇴소)가 마감되었습니다! 최종 종합 리포트를 확인하세요.",
                related_url=f"/quiz/manager/cohort/{cohort.id}/report/" # 추후 만들 리포트 페이지 URL
            )