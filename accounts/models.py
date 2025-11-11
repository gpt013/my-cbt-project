from django.db import models
from django.contrib.auth.models import User
import re

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
    
    # --- 여기가 수정된 부분입니다 ---
    process = models.ForeignKey(
        "Process",  # Process -> "Process" (따옴표 추가)
        on_delete=models.SET_NULL,
        null=True, blank=True,
        verbose_name='담당 공정'
    )
    # -----------------------------

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

# --- [핵심 추가] 5. '평가 기록 유형' 모델 (새로 추가) ---
# '경고', '시상' 등을 관리자가 직접 추가/삭제할 수 있도록 별도 모델로 분리
class RecordType(models.Model):
    name = models.CharField(max_length=50, unique=True, verbose_name="기록 유형 이름")
    
    class Meta:
        verbose_name = "평가 기록 유형"
        verbose_name_plural = "평가 기록 유형"
    
    def __str__(self):
        return self.name

# --- 기존 모델 6: Profile (누락 없음) ---
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

    def save(self, *args, **kwargs):
        self.class_number = re.sub(r'[^0-9]', '', self.class_number)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.username}의 프로필"

# --- [핵심 수정] 7. '평가 기록' 모델 (RecordType 수정) ---
class EvaluationRecord(models.Model):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, verbose_name="프로필")
    
    # --- [수정] 고정된 TextChoices를 삭제합니다 ---
    # class RecordType(models.TextChoices): ... (이 블록 전체 삭제)

    # --- [수정] CharField를 ForeignKey로 변경합니다 ---
    record_type = models.ForeignKey(
        RecordType, 
        on_delete=models.SET_NULL, # 유형이 삭제되어도 기록은 남도록
        null=True, blank=False, # 비어있을 순 없지만, models.py 호환성을 위해 null=True
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