from django.db import models
from django.conf import settings
from accounts.models import Profile
from django.utils import timezone

# ▼▼▼ [이 부분들이 누락되어 에러가 났습니다] ▼▼▼
from django.db.models import Sum
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
# ▲▲▲ ------------------------------------- ▲▲▲

# 1. 근무 유형 (관리자가 커스텀 가능)
class WorkType(models.Model):
    name = models.CharField(max_length=50, verbose_name="근무 명칭")
    short_name = models.CharField(max_length=10, verbose_name="약어")
    color = models.CharField(max_length=7, default="#FFFFFF", verbose_name="표시 색상(HEX)")
    deduction = models.FloatField(default=0.0, verbose_name="연차 차감일수")
    is_working_day = models.BooleanField(default=True, verbose_name="출근 인정 여부")
    order = models.PositiveIntegerField(default=0, verbose_name="정렬 순서")

    class Meta:
        verbose_name = "근무 유형 설정"
        verbose_name_plural = "근무 유형 설정"
        ordering = ['order']

    def __str__(self):
        return f"{self.name} ({self.deduction})"


# 2. 일별 스케줄 (핵심 테이블)
class DailySchedule(models.Model):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, verbose_name="교육생")
    date = models.DateField(verbose_name="날짜")
    
    # 계획된 근무
    work_type = models.ForeignKey(WorkType, on_delete=models.SET_NULL, null=True, verbose_name="근무 일정")
    
    # MDM 인증 정보
    mdm_image = models.ImageField(upload_to='mdm_proofs/%Y/%m/%d/', null=True, blank=True, verbose_name="MDM 인증샷")
    captured_time = models.DateTimeField(null=True, blank=True, verbose_name="OCR 인식 시간")
    
    # 상태 판정
    is_late = models.BooleanField(default=False, verbose_name="지각 여부")
    is_absent = models.BooleanField(default=False, verbose_name="결석 여부")
    is_mdm_verified = models.BooleanField(default=False, verbose_name="보안 인증 완료")
    
    memo = models.CharField(max_length=200, blank=True, verbose_name="비고")

    class Meta:
        unique_together = ('profile', 'date')
        verbose_name = "일별 근태 스케줄"
        verbose_name_plural = "일별 근태 스케줄"
        ordering = ['date']

    def __str__(self):
        return f"{self.date} - {self.profile.name}"


# 3. 당일 변경 요청 (승인제)
class ScheduleRequest(models.Model):
    STATUS_CHOICES = [('pending', '대기중'), ('approved', '승인됨'), ('rejected', '거절됨')]
    
    requester = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name='schedule_requests')
    date = models.DateField(verbose_name="변경 대상 날짜")
    target_work_type = models.ForeignKey(WorkType, on_delete=models.CASCADE, verbose_name="변경할 근무")
    reason = models.TextField(verbose_name="변경 사유 (필수)")
    
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    approver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="승인자")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "근무 변경 요청"
        verbose_name_plural = "근무 변경 요청"


# 4. 연차 관리 (잔여 개수)
class LeaveQuota(models.Model):
    profile = models.OneToOneField(Profile, on_delete=models.CASCADE, verbose_name="교육생")
    total_leave = models.FloatField(default=15.0, verbose_name="총 연차")
    used_leave = models.FloatField(default=0.0, verbose_name="사용 연차")
    
    @property
    def remaining_leave(self):
        return self.total_leave - self.used_leave

    class Meta:
        verbose_name = "연차 현황"
        verbose_name_plural = "연차 현황"


# [신규] 스케줄 변경 시 연차 사용량 자동 재계산 Signal
@receiver(post_save, sender=DailySchedule)
@receiver(post_delete, sender=DailySchedule)
def update_leave_usage(sender, instance, **kwargs):
    profile = instance.profile
    
    # 1. 해당 교육생의 모든 스케줄 중 '차감일수(deduction)'가 있는 것들을 다 더합니다.
    total_used = DailySchedule.objects.filter(profile=profile).aggregate(
        total=Sum('work_type__deduction')
    )['total'] or 0.0
    
    # 2. 연차 통장(LeaveQuota) 갱신
    quota, created = LeaveQuota.objects.get_or_create(profile=profile)
    
    if quota.used_leave != total_used:
        quota.used_leave = total_used
        quota.save()
        print(f"🔄 [연차 갱신] {profile.name}: 사용 {total_used}일 / 잔여 {quota.remaining_leave}일")

class Attendance(models.Model):
    """
    [신규] 스마트 출근 인증 기록 (GPS + MDM)
    - 기존 DailySchedule과 별도로, 실제 '출근 찍은 시간'을 기록합니다.
    """
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='attendance_records')
    date = models.DateField(default=timezone.now) # 출근 날짜
    check_in_time = models.DateTimeField(null=True, blank=True) # 실제 찍은 시간
    daily_schedule = models.ForeignKey('DailySchedule', on_delete=models.SET_NULL, null=True, blank=True)
    # 상태 (출근/지각/조퇴/결석)
    status = models.CharField(max_length=20, default='미출근') 
    
    # 인증 여부 (True: GPS+MDM 통과)
    is_verified = models.BooleanField(default=False) 

    class Meta:
        # 하루에 중복 출근 방지
        unique_together = ('user', 'date') 
        verbose_name = '출근 기록'
        verbose_name_plural = '출근 기록 목록'

    def __str__(self):
        return f"{self.user.username} - {self.date} ({self.status})"
    
