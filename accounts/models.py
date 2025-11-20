from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
import re
from django.dispatch import receiver

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
        Process, # (문자열 대신 객체 직접 참조)
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
    
    # --- [수정] class_number(Text) -> cohort(ForeignKey) ---
    # (기존 class_number는 주석 처리하거나 삭제)
    # class_number = models.CharField(max_length=50, verbose_name='기수')
    
    cohort = models.ForeignKey(
        Cohort, 
        on_delete=models.SET_NULL, 
        null=True, blank=False, 
        verbose_name="소속 기수"
    )
    # ------------------------------------------------------

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

# A. 평가 항목 (예: 인성, 실습, 근태)
class EvaluationCategory(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="평가 항목")
    order = models.PositiveIntegerField(default=0, verbose_name="표시 순서")

    class Meta:
        verbose_name = "매니저 평가 항목"
        verbose_name_plural = "매니저 평가 항목 (대분류)"
        ordering = ['order']

    def __str__(self):
        return self.name

# B. 평가 세부 내용 (체크리스트 예시)
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
    # [체크리스트] 매니저가 선택한 항목들
    selected_items = models.ManyToManyField(
        EvaluationItem, 
        blank=True, 
        verbose_name="선택된 평가 항목"
    )
    # [정성 평가]
    overall_comment = models.TextField(verbose_name="종합 정성 평가 (코멘트)")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="작성일시")

    class Meta:
        verbose_name = "매니저 최종 평가서"
        verbose_name_plural = "매니저 최종 평가서"
        ordering = ['-created_at']

    def __str__(self):
        manager_name = self.manager.username if self.manager else "알 수 없음"
        return f"{self.trainee_profile.name} 평가 ({manager_name})"


# --- Signal ---
@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    if not hasattr(instance, 'profile'):
        Profile.objects.create(user=instance)
    instance.profile.save()