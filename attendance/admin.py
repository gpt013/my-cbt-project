from django.contrib import admin
from .models import WorkType, DailySchedule, ScheduleRequest, LeaveQuota

@admin.register(WorkType)
class WorkTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'short_name', 'color', 'deduction', 'is_working_day', 'order')
    list_editable = ('color', 'deduction', 'order')
    ordering = ('order',)

@admin.register(DailySchedule)
class DailyScheduleAdmin(admin.ModelAdmin):
    list_display = ('date', 'profile', 'work_type', 'is_mdm_verified', 'is_late')
    list_filter = ('date', 'work_type', 'profile__process')
    search_fields = ('profile__name',)

@admin.register(ScheduleRequest)
class ScheduleRequestAdmin(admin.ModelAdmin):
    list_display = ('requester', 'date', 'target_work_type', 'status', 'created_at')
    list_filter = ('status', 'date')
    actions = ['approve_requests']

    @admin.action(description='선택된 요청 승인 및 반영')
    def approve_requests(self, request, queryset):
        for req in queryset:
            if req.status == 'pending':
                # 스케줄 업데이트
                schedule, created = DailySchedule.objects.get_or_create(
                    profile=req.requester, date=req.date
                )
                schedule.work_type = req.target_work_type
                schedule.save()
                
                # 요청 상태 변경
                req.status = 'approved'
                req.approver = request.user
                req.save()
                
                # (추가 기능) 연차 차감 로직은 signals나 save() 오버라이딩으로 처리 예정

@admin.register(LeaveQuota)
class LeaveQuotaAdmin(admin.ModelAdmin):
    list_display = ('profile', 'total_leave', 'used_leave', 'remaining_leave')
    search_fields = ('profile__name',)