from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
import re
# --- [핵심 1] Signal을 위한 'receiver' import 추가 ---
from django.dispatch import receiver
# -----------------------------------------------

# --- 기존 모델 1: Company (누락 없음) ---
class Company(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="회사 이름")
    class Meta:
        verbose_name = "회사"
        verbose_name_plural = "회사"
    def __str__(self):
        return self.name

# --- 기존 모델 2: Badge (누락 없음) ---
class Badge(models.Model):
    name = models.CharField(max_length=100, verbose_name="뱃지 이름")
    description = models.TextField(verbose_name="획득 조건 설명")
    image = models.ImageField(upload_to='badges/', blank=True, null=True, verbose_name="뱃지 이미지")
    class Meta:
        verbose_name = "뱃지"
        verbose_name_plural = "뱃지"
    def __str__(self):
        return self.name

# --- 기존 모델 3: PartLeader (누락 없음) ---
class PartLeader(models.Model):
    name = models.CharField(max_length=50, unique=True, verbose_name="PL 이름")
    email = models.EmailField(unique=True, verbose_name="PL 이메일", help_text="2회 불합격 시 이 이메일로 알림이 갑니다.")
    company = models.ForeignKey(Company, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="소속 회사")
    
    process = models.ForeignKey(
        "Process",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        verbose_name='담당 공정'
    )

    class Meta:
        verbose_name = "PL(파트장)"
        verbose_name_plural = "PL(파트장)"
    def __str__(self):
        return self.name

# --- 기존 모델 4: Process (누락 없음) ---
class Process(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="공정 이름")
    class Meta:
        verbose_name = "공정"
        verbose_name_plural = "공정"
    def __str__(self):
        return self.name

# --- [핵심 추가] 5. '평가 기록 유형' 모델 (누락 없음) ---
class RecordType(models.Model):
    name = models.CharField(max_length=50, unique=True, verbose_name="기록 유형 이름")
    
    class Meta:
        verbose_name = "평가 기록 유형"
        verbose_name_plural = "평가 기록 유형"
    
    def __str__(self):
        return self.name

# --- 기존 모델 6: Profile (is_profile_complete 필드 추가) ---
class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    company = models.ForeignKey(Company, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="소속 회사")
    name = models.CharField(max_length=50, verbose_name='이름')
    employee_id = models.CharField(max_length=50, verbose_name='사번')
    class_number = models.CharField(max_length=50, verbose_name='기수')
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

    # --- [핵심 2] '프로필 완성' 플래그 필드 추가 ---
    is_profile_complete = models.BooleanField(
        default=False, 
        verbose_name="프로필 작성 완료"
    )
    # -----------------------------------------

    def save(self, *args, **kwargs):
        self.class_number = re.sub(r'[^0-9]', '', self.class_number)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.username}의 프로필"

# --- [핵심 수정] 7. '평가 기록' 모델 (누락 없음) ---
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


# --- [핵심 3] User 생성 시 Profile 자동 생성/저장 Signal 추가 ---

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """
    새로운 User가 생성될 때(created=True),
    그 User와 연결된 빈 Profile을 자동으로 생성합니다.
    """
    if created:
        Profile.objects.create(user=instance)

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    """
    User가 저장될 때, 연결된 Profile도 함께 저장합니다.
    """
    # (Profile이 없는 User가 저장될 경우를 대비해, 없으면 생성하도록 안전장치 추가)
    if not hasattr(instance, 'profile'):
        Profile.objects.create(user=instance)
    instance.profile.save()
# --------------------------------------------------------