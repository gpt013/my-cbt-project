from django.db import models
from django.contrib.auth.models import User, Group, Permission 
from django.contrib.contenttypes.models import ContentType 
from django.db.models.signals import post_save
from django.dispatch import receiver
# quiz 앱의 모델들은 권한 부여 로직에서만 import (순환 참조 방지 위해 함수 내부 import 권장)

# --- [신규] 기수(Cohort) 모델 ---
class Cohort(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="기수 이름 (예: 25-01기)")
    start_date = models.DateField(verbose_name="교육 시작일")
    end_date = models.DateField(verbose_name="교육 종료일", null=True, blank=True)
    is_registration_open = models.BooleanField(
        default=True, 
        verbose_name="가입 활성화 여부",
        help_text="이 옵션을 체크해야 해당 기수 인원이 가입할 수 있습니다."
    )

    class Meta:
        verbose_name = "기수 (교육 차수)"
        verbose_name_plural = "기수 (교육 차수)"
        ordering = ['-start_date']

    def __str__(self):
        return f"{self.name} ({self.start_date})"

# --- 기존 모델 1: Company ---
class Company(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="회사 이름")
    class Meta:
        verbose_name = "회사"
        verbose_name_plural = "회사"
    def __str__(self):
        return self.name

# --- 기존 모델 2: Badge ---
class Badge(models.Model):
    name = models.CharField(max_length=100, verbose_name="뱃지 이름")
    description = models.TextField(verbose_name="획득 조건 설명")
    image = models.ImageField(upload_to='badges/', blank=True, null=True, verbose_name="뱃지 이미지")
    class Meta:
        verbose_name = "뱃지"
        verbose_name_plural = "뱃지"
    def __str__(self):
        return self.name

# --- 기존 모델 4: Process (순서 변경: PartLeader에서 참조하므로 위로 올림) ---
class Process(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="공정 이름")
    class Meta:
        verbose_name = "공정"
        verbose_name_plural = "공정"
    def __str__(self):
        return self.name

# --- 기존 모델 3: PartLeader ---
class PartLeader(models.Model):
    name = models.CharField(max_length=50, unique=True, verbose_name="PL 이름")
    email = models.EmailField(unique=True, verbose_name="PL 이메일", help_text="2회 불합격 시 이 이메일로 알림이 갑니다.")
    company = models.ForeignKey(Company, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="소속 회사")
    
    process = models.ForeignKey(
        Process, 
        on_delete=models.SET_NULL,
        null=True, blank=True,
        verbose_name='담당 공정'
    )

    class Meta:
        verbose_name = "PL(파트장)"
        verbose_name_plural = "PL(파트장)"
    def __str__(self):
        return self.name


# --- 기존 모델 5: RecordType ---
class RecordType(models.Model):
    name = models.CharField(max_length=50, unique=True, verbose_name="기록 유형 이름")
    class Meta:
        verbose_name = "평가 기록 유형"
        verbose_name_plural = "평가 기록 유형"
    def __str__(self):
        return self.name

# --- 기존 모델 6: Profile (Cohort 필드 추가) ---
class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    company = models.ForeignKey(Company, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="소속 회사")
    name = models.CharField(max_length=50, verbose_name='이름')
    employee_id = models.CharField(max_length=50, verbose_name='사번')
    
    cohort = models.ForeignKey(
        Cohort, 
        on_delete=models.SET_NULL, 
        null=True, blank=False, 
        verbose_name="소속 기수"
    )

    process = models.ForeignKey(
        Process, 
        on_delete=models.SET_NULL, 
        null=True, blank=True, 
        verbose_name="공정"
    )
    line = models.CharField(max_length=100, verbose_name='라인', blank=True, null=True)
    pl = models.ForeignKey(
        PartLeader, 
        on_delete=models.SET_NULL, 
        null=True, blank=True, 
        verbose_name="담당 PL"
    )

    badges = models.ManyToManyField(Badge, blank=True, verbose_name="획득한 뱃지")
    ai_summary = models.TextField(verbose_name="AI 종합 의견", blank=True, null=True, help_text="AI가 생성한 교육생 종합 평가입니다.")

    is_profile_complete = models.BooleanField(
        default=False, 
        verbose_name="프로필 작성 완료"
    )
    
    # ▼▼▼ [추가] 매니저 여부 체크박스 ▼▼▼
    is_manager = models.BooleanField(default=False, verbose_name="매니저 권한 여부")
    must_change_password = models.BooleanField(default=False, verbose_name="비밀번호 변경 필요")

    def __str__(self):
        return f"{self.user.username}의 프로필"


# --- 기존 모델 7: EvaluationRecord ---
class EvaluationRecord(models.Model):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, verbose_name="프로필")
    record_type = models.ForeignKey(
        RecordType, 
        on_delete=models.SET_NULL,
        null=True, blank=False,
        verbose_name="기록 유형"
    )
    description = models.TextField(verbose_name="세부 내용 (필수)", blank=False, null=False)
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="기록 일시")

    class Meta:
        verbose_name = "평가 기록"
        verbose_name_plural = "평가 기록"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.profile.user.username} - {self.record_type.name if self.record_type else '미분류'}"


# --- [신규] 매니저 평가 시스템 모델들 ---

# A. 평가 항목
class EvaluationCategory(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="평가 항목")
    order = models.PositiveIntegerField(default=0, verbose_name="표시 순서")

    class Meta:
        verbose_name = "매니저 평가 항목"
        verbose_name_plural = "매니저 평가 항목 (대분류)"
        ordering = ['order']

    def __str__(self):
        return self.name

# B. 평가 세부 내용
class EvaluationItem(models.Model):
    category = models.ForeignKey(EvaluationCategory, on_delete=models.CASCADE, verbose_name="평가 항목")
    description = models.CharField(max_length=255, verbose_name="평가 예시 (체크할 내용)")
    is_positive = models.BooleanField(default=True, verbose_name="긍정/부정 (장점/단점)")

    class Meta:
        verbose_name = "매니저 평가 예시"
        verbose_name_plural = "매니저 평가 예시 (체크리스트)"
        ordering = ['category__order', 'id']

    def __str__(self):
        return f"[{self.category.name}] {self.description}"

# C. 매니저 최종 평가서
class ManagerEvaluation(models.Model):
    trainee_profile = models.ForeignKey(
        Profile, 
        on_delete=models.CASCADE, 
        verbose_name="평가 대상 교육생"
    )
    manager = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        verbose_name="평가자 (매니저)"
    )
    selected_items = models.ManyToManyField(
        EvaluationItem, 
        blank=True, 
        verbose_name="선택된 평가 항목"
    )
    overall_comment = models.TextField(verbose_name="종합 정성 평가 (코멘트)")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="작성일시")

    class Meta:
        verbose_name = "매니저 최종 평가서"
        verbose_name_plural = "매니저 최종 평가서"
        ordering = ['-created_at']

    def __str__(self):
        manager_name = self.manager.username if self.manager else "알 수 없음"
        return f"{self.trainee_profile.name} 평가 ({manager_name})"


# --- [신규] 권한 요청 모델 (티켓 시스템) ---
class ProcessAccessRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', '대기중'),
        ('approved', '승인됨 (미사용)'), # 아직 안 씀
        ('expired', '사용완료 (만료)'), # 1회 사용 후 변환됨
        ('rejected', '거절됨'),
    ]

    # [수정] requester 필드 추가 (누가 요청했는지)
    requester = models.ForeignKey(User, on_delete=models.CASCADE, related_name='access_requests')
    
    # [수정] target_process: null=True 허용 (전체 요청 시 비워둠)
    target_process = models.ForeignKey('accounts.Process', on_delete=models.CASCADE, null=True, blank=True)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        # 이름 표시할 때도 에러 안 나게 처리
        target_name = self.target_process.name if self.target_process else "🌍 전체 공정"
        return f"{self.requester.profile.name} -> {target_name} ({self.status})"


# --- Signal (자동화 로직) ---

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    if not hasattr(instance, 'profile'):
        Profile.objects.create(user=instance)
    instance.profile.save()

# ▼▼▼ [핵심] 매니저 권한 자동 부여 Signal ▼▼▼
@receiver(post_save, sender=Profile)
def manage_permissions(sender, instance, created, **kwargs):
    user = instance.user
    
    # 1. '매니저' 그룹 가져오기 (없으면 생성)
    manager_group, group_created = Group.objects.get_or_create(name='매니저')

    # ---------------------------------------------------------------
    # [핵심 수정] 매니저 그룹에 '안전한 실무 권한'만 부여하기
    # (관리자 권한, 그룹 권한 등 위험한 건 제외)
    # ---------------------------------------------------------------
    if group_created:
        # 모델들을 불러옵니다 (순환 참조 방지)
        from quiz.models import (
            Quiz, Question, Choice, ExamSheet, Tag,  # 문제 관리
            QuizAttempt, TestResult                  # 응시 및 결과 관리
        )
        from accounts.models import (
            Profile, PartLeader,                     # 교육생 관리
            ManagerEvaluation, EvaluationRecord      # 평가 관리
        )

        # [1] 완전 관리 권한 (추가/수정/삭제/조회) 부여할 모델들
        # -> 문제 출제, 태그, PL 관리, 평가서 작성 등은 자유롭게 가능
        full_access_models = [
            Quiz, Question, Choice, ExamSheet, Tag,  # 퀴즈 관련
            PartLeader,                              # PL 관리
            ManagerEvaluation, EvaluationRecord      # 평가 관련
        ]
        
        for model in full_access_models:
            ct = ContentType.objects.get_for_model(model)
            perms = Permission.objects.filter(content_type=ct) # CRUD 전체 부여
            manager_group.permissions.add(*perms)

        # [2] 결과 및 요청 관리 (수정/조회/삭제) - 추가(Add)는 시스템이 하므로 제외 가능하지만 편의상 줌
        # -> 최종 결과 수정/삭제, 응시 요청 승인 등
        result_models = [TestResult, QuizAttempt]
        for model in result_models:
            ct = ContentType.objects.get_for_model(model)
            perms = Permission.objects.filter(content_type=ct)
            manager_group.permissions.add(*perms)

        # [3] 프로필 관리 (수정/조회만 가능) - ★삭제(Delete) 권한은 위험하므로 제외★
        # -> 매니저가 교육생 정보를 수정하거나 승인할 수는 있지만, 계정을 삭제하진 못하게 함
        ct_profile = ContentType.objects.get_for_model(Profile)
        perms_profile = Permission.objects.filter(
            content_type=ct_profile, 
            codename__in=['change_profile', 'view_profile']
        )
        manager_group.permissions.add(*perms_profile)

        

        manager_group.save()
        print("✅ 매니저 그룹에 '안전한 실무 권한'이 자동 부여되었습니다.")

    # ---------------------------------------------------------------
    # [기존 로직] 사용자에게 그룹 및 스태프 권한 부여
    # ---------------------------------------------------------------
    if instance.is_manager:
        if not user.is_staff:
            user.is_staff = True
            user.save()
        if not user.groups.filter(name='매니저').exists():
            user.groups.add(manager_group)
    else:
        if not user.is_superuser:
            if user.is_staff:
                user.is_staff = False
                user.save()
            if user.groups.filter(name='매니저').exists():
                user.groups.remove(manager_group)