from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User, Group
from django.urls import reverse
from django.utils.html import format_html

# 모델들 Import (StudentLog 추가, Interview 제거)
from .models import (
    Profile, Badge, Company, EvaluationRecord, PartLeader, Process, RecordType, 
    Cohort, EvaluationCategory, EvaluationItem, ManagerEvaluation, FinalAssessment,
     ProcessAccessRequest 
)
from quiz.models import Quiz, TestResult

# -----------------------------------------------------------
# [1] 커스텀 액션 (Action) 함수 정의
# -----------------------------------------------------------

@admin.action(description='✅ 선택된 교육생 가입 승인 (계정 활성화)')
def activate_users(modeladmin, request, queryset):
    # (ProfileAdmin에서 호출될 경우)
    if modeladmin.model == Profile:
        count = 0
        for profile in queryset:
            user = profile.user
            if not user.is_active:
                user.is_active = True
                user.save()
                count += 1
        if count > 0:
            modeladmin.message_user(request, f"🎉 {count}명의 계정을 활성화했습니다.")
        else:
            modeladmin.message_user(request, "이미 활성화된 계정들입니다.", level='warning')
            
    # (UserAdmin에서 호출될 경우 - 슈퍼유저용)
    elif modeladmin.model == User:
        queryset.update(is_active=True)
        modeladmin.message_user(request, "선택된 사용자들을 활성화했습니다.")

@admin.action(description='🔐 선택한 사용자의 비밀번호를 "1234"로 초기화 (강제 변경 설정)')
def reset_password_to_default(modeladmin, request, queryset):
    if not request.user.is_staff:
        return
        
    count = 0
    for obj in queryset:
        target_user = obj.user if isinstance(obj, Profile) else obj
        
        # [보안] 슈퍼유저는 초기화 불가
        if target_user.is_superuser:
            continue

        target_user.set_password('1234')
        target_user.save()
        
        # 강제 변경 플래그 설정
        if hasattr(target_user, 'profile'):
            target_user.profile.must_change_password = True
            target_user.profile.save()
            
        count += 1
    
    if count > 0:
        modeladmin.message_user(request, f"✅ {count}명의 비밀번호가 '1234'로 초기화되었습니다.")
    else:
        modeladmin.message_user(request, "⚠️ 슈퍼유저는 초기화할 수 없습니다.", level='error')

@admin.action(description='💬 선택한 인원 메신저 켜기 (ON)')
def enable_messenger(modeladmin, request, queryset):
    updated = queryset.update(can_use_messenger=True)
    modeladmin.message_user(request, f"✅ {updated}명의 메신저 권한을 켰습니다.")

@admin.action(description='🚫 선택한 인원 메신저 끄기 (OFF)')
def disable_messenger(modeladmin, request, queryset):
    updated = queryset.update(can_use_messenger=False)
    modeladmin.message_user(request, f"⛔ {updated}명의 메신저 권한을 껐습니다.")

@admin.action(description='🎓 선택된 교육생 일괄 수료 처리 (재직 인원만)')
def mark_as_completed(modeladmin, request, queryset):
    if not request.user.is_staff: return
    count = 0
    skipped = 0
    for profile in queryset:
        if profile.status == 'attending':
            profile.status = 'completed'
            profile.save()
            count += 1
        else:
            skipped += 1
    if count > 0: modeladmin.message_user(request, f"🎉 {count}명 수료 처리 완료.")
    if skipped > 0: modeladmin.message_user(request, f"⚠️ {skipped}명 제외됨 (재직 상태 아님).", level='warning')


# -----------------------------------------------------------
# [2] 기본 정보 모델 관리자
# -----------------------------------------------------------

@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',) 

@admin.register(Badge)
class BadgeAdmin(admin.ModelAdmin):
    list_display = ('name', 'description')
    search_fields = ('name',)

@admin.register(PartLeader)
class PartLeaderAdmin(admin.ModelAdmin):
    # 1. process 대신 get_process 사용
    list_display = ('name', 'email', 'company', 'get_process')
    list_filter = ('company', 'process') 
    
    # 2. 사용자님이 원래 쓰시던 훌륭한 검색 조건 그대로 유지!
    search_fields = ('name', 'email', 'company__name', 'process__name') 
    autocomplete_fields = ('company', 'process') 

    # 3. 여러 공정을 쉼표로 묶어서 보여주는 함수
    def get_process(self, obj):
        return ", ".join([p.name for p in obj.process.all()])
    get_process.short_description = '담당 공정'

@admin.register(Process)
class ProcessAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',) 

@admin.register(RecordType)
class RecordTypeAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)

@admin.register(Cohort)
class CohortAdmin(admin.ModelAdmin):
    # ★ 핵심 1: list_display를 딱 한 번만 쓰고, 필요한 걸 다 넣었습니다.
    list_display = ('name', 'start_date', 'end_date', 'is_registration_open', 'is_manual_exam_allowed')
    list_filter = ('is_registration_open', 'start_date')
    
    # ★ 핵심 2: list_editable도 딱 한 번만 쓰고, 두 개 다 넣었습니다.
    list_editable = ('is_registration_open', 'is_manual_exam_allowed') 
    
    search_fields = ('name',)
    ordering = ('-start_date',)

# -----------------------------------------------------------
# [3] 매니저 평가 시스템 관리자
# -----------------------------------------------------------

@admin.register(EvaluationCategory)
class EvaluationCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'order')
    list_editable = ('order',)

@admin.register(EvaluationItem)
class EvaluationItemAdmin(admin.ModelAdmin):
    list_display = ('description', 'category', 'is_positive')
    list_filter = ('category', 'is_positive')
    search_fields = ('description',)

@admin.register(ManagerEvaluation)
class ManagerEvaluationAdmin(admin.ModelAdmin):
    list_display = ('trainee_profile', 'manager', 'created_at')
    list_filter = ('manager',)
    search_fields = ('trainee_profile__name', 'manager__username')
    filter_horizontal = ('selected_items',)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "manager":
            kwargs["queryset"] = User.objects.filter(is_staff=True)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


# -----------------------------------------------------------
# [4] 프로필(Profile) 관리자 - ★ 매니저 주 활동 영역 ★
# -----------------------------------------------------------

# [중요] FinalAssessmentInline을 ProfileAdmin보다 먼저 정의해야 에러가 안 남!
class FinalAssessmentInline(admin.StackedInline):
    model = FinalAssessment
    can_delete = False
    verbose_name_plural = "최종 종합 평가서 (점수 입력)"
    
    readonly_fields = ('exam_avg_score', 'final_score', 'rank', 'updated_at')
    fields = (
        ('exam_avg_score', 'final_score', 'rank'), # 보기 전용 (자동)
        ('practice_score', 'note_score', 'attitude_score'), # 입력 가능 (수동)
        'manager_comment'
    )
    extra = 0

@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    # [수정] is_approved(승인여부)를 리스트에 표시
    list_display = ('user', 'name', 'company', 'get_cohort', 'get_process_name', 'status', 'warning_count', 'is_approved', 'is_profile_complete', 'get_is_active', 'is_manager')
    
    # [수정] is_approved를 체크박스로 바로 수정 가능하게 추가 (빠른 승인 처리)
    list_editable = ('status', 'warning_count', 'is_approved') 

    # 인라인 연결 (기존 유지)
    inlines = [FinalAssessmentInline] 

    search_fields = ('user__username', 'name', 'employee_id', 'cohort__name')
    
    # [수정] 필터에 승인 여부 추가 (미승인 인원만 보기 편함)
    list_filter = ('is_approved', 'status', 'user__is_active', 'is_manager', 'must_change_password', 'process', 'cohort', 'company')
    
    autocomplete_fields = ('user', 'company', 'process', 'pl', 'cohort')
    filter_horizontal = ('badges',)

    # 액션 추가 (기존 유지)
    actions = [
        activate_users, 
        reset_password_to_default, 
        mark_as_completed, 
        enable_messenger, 
        disable_messenger
    ]

    # [보안 1] 매니저에게는 '슈퍼유저' 목록 숨김
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(user__is_superuser=False)

    # [보안 2] 수정 권한 제한
    def get_readonly_fields(self, request, obj=None):
        if request.user.is_superuser:
            return ()
        # 일반 매니저용 읽기 전용 필드 (수정 불가, 눈으로만 확인)
        return (
            'user', 
            'is_manager', 
            'must_change_password', 
            'badges', 
            'is_pl',               
            'is_profile_complete'  
        )

    # [보안 3] URL 조작 방지
    def has_change_permission(self, request, obj=None):
        if obj and obj.user.is_superuser and not request.user.is_superuser:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj and obj.user.is_superuser and not request.user.is_superuser:
            return False
        return super().has_delete_permission(request, obj)

    # --- Display Helper Methods ---
    @admin.display(description='승인 상태', boolean=True)
    def get_is_active(self, obj):
        return obj.user.is_active

    @admin.display(description='기수', ordering='cohort__name')
    def get_cohort(self, obj):
        return obj.cohort.name if obj.cohort else '-'

    @admin.display(description='공정', ordering='process__name')
    def get_process_name(self, obj):
        return obj.process.name if obj.process else '-'


# -----------------------------------------------------------
# [5] 평가 기록 (EvaluationRecord)
# -----------------------------------------------------------
@admin.register(EvaluationRecord)
class EvaluationRecordAdmin(admin.ModelAdmin):
    list_display = ('profile_name', 'get_record_type', 'description_snippet', 'created_at')
    list_filter = ('record_type', 'profile__company', 'profile__cohort', 'profile__process', 'profile__pl')
    search_fields = ('profile__user__username', 'profile__name', 'description')
    autocomplete_fields = ('profile',) 

    @admin.display(description='교육생 이름', ordering='profile__name')
    def profile_name(self, obj):
        return obj.profile.name
    
    @admin.display(description='기록 유형', ordering='record_type__name')
    def get_record_type(self, obj):
        return obj.record_type.name if obj.record_type else ''

    @admin.display(description='세부 내용')
    def description_snippet(self, obj):
        return obj.description[:30] + "..." if len(obj.description) > 30 else obj.description


# -----------------------------------------------------------
# [6] 그룹(Group) 및 사용자(User) - 슈퍼유저용
# -----------------------------------------------------------

# (UserInline: 그룹 내 사용자 보기용)
class UserInline(admin.TabularInline):
    model = User.groups.through
    verbose_name = "소속된 교육생"
    verbose_name_plural = "소속된 교육생 목록"
    readonly_fields = ('user_link', 'name', 'employee_id', 'get_cohort', 'get_company', 'process', 'get_pl', 'first_attempt_scores')
    can_delete = False
    max_num = 0
    exclude = ('user',)

    @admin.display(description='사용자 ID')
    def user_link(self, instance):
        link = reverse("admin:auth_user_change", args=[instance.user.id])
        return format_html('<a href="{}">{}</a>', link, instance.user.username)
    @admin.display(description='이름')
    def name(self, instance):
        return instance.user.profile.name if hasattr(instance.user, 'profile') else ''
    @admin.display(description='사번')
    def employee_id(self, instance):
        return instance.user.profile.employee_id if hasattr(instance.user, 'profile') else ''
    
    @admin.display(description='기수')
    def get_cohort(self, instance):
        if hasattr(instance.user, 'profile') and instance.user.profile.cohort:
            return instance.user.profile.cohort.name
        return ''
        
    @admin.display(description='소속 회사')
    def get_company(self, instance):
        if hasattr(instance.user, 'profile') and instance.user.profile.company:
            return instance.user.profile.company.name
        return ''
    @admin.display(description='공정')
    def process(self, instance):
        if hasattr(instance.user, 'profile') and instance.user.profile.process:
            return instance.user.profile.process.name
        return ''
    @admin.display(description='담당 PL')
    def get_pl(self, instance):
        if hasattr(instance.user, 'profile') and instance.user.profile.pl:
            return instance.user.profile.pl.name
        return ''
    @admin.display(description='시험별 1차 점수')
    def first_attempt_scores(self, instance):
        user = instance.user
        scores_html = "<ul style='margin:0; padding-left: 1.2em;'>"
        all_quizzes = Quiz.objects.all()
        for quiz in all_quizzes:
            first_attempt = TestResult.objects.filter(user=user, quiz=quiz).order_by('completed_at').first()
            score = f"<strong>{first_attempt.score}점</strong>" if first_attempt else "미응시"
            scores_html += f"<li>{quiz.title}: {score}</li>"
        scores_html += "</ul>"
        return format_html(scores_html)

class CustomGroupAdmin(admin.ModelAdmin):
    filter_horizontal = ('permissions',)
    inlines = [UserInline]
    list_display = ['name']
    search_fields = ('name',)
    ordering = ('name',)

# (ProfileInline: 사용자 상세 내 프로필 표시용)
class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    verbose_name_plural = '추가 정보'
    filter_horizontal = ('badges',)
    fields = ('is_profile_complete', 'company', 'name', 'employee_id', 'cohort', 'process', 'line', 'pl', 'badges')
    autocomplete_fields = ('company', 'process', 'pl', 'cohort') 

class UserAdmin(BaseUserAdmin):
    inlines = (ProfileInline,)
    list_display = ('username', 'name', 'employee_id', 'get_cohort', 'get_company', 'get_process', 'get_pl', 'is_staff', 'is_active')
    list_filter = ('is_active', 'is_staff', 'groups', 'profile__company', 'profile__cohort', 'profile__process', 'profile__pl')
    search_fields = ('username', 'profile__name', 'profile__employee_id')
    ordering = ('-is_staff', 'username')
    
    # 액션 추가
    actions = [activate_users, reset_password_to_default]
    
    @admin.display(description='소속 회사', ordering='profile__company__name')
    def get_company(self, obj):
        if hasattr(obj, 'profile') and obj.profile.company:
            return obj.profile.company.name
        return ''
    @admin.display(description='공정', ordering='profile__process__name')
    def get_process(self, obj):
        if hasattr(obj, 'profile') and obj.profile.process:
            return obj.profile.process.name
        return ''
    @admin.display(description='담당 PL', ordering='profile__pl__name')
    def get_pl(self, obj):
        if hasattr(obj, 'profile') and obj.profile.pl:
            return obj.profile.pl.name
        return ''
    
    @admin.display(description='기수', ordering='profile__cohort__name')
    def get_cohort(self, obj):
        if hasattr(obj, 'profile') and obj.profile.cohort:
            return obj.profile.cohort.name
        return ''

    def name(self, obj):
        if hasattr(obj, 'profile'):
            return obj.profile.name
        return ''
    name.short_description = '이름'
    def employee_id(self, obj):
        if hasattr(obj, 'profile'):
            return obj.profile.employee_id
        return ''
    employee_id.short_description = '사번'


@admin.register(ProcessAccessRequest)
class ProcessAccessRequestAdmin(admin.ModelAdmin):
    list_display = ('requester', 'target_process', 'status', 'created_at')
    list_filter = ('status',)


# 최종 등록 (User, Group)
admin.site.unregister(User)
admin.site.register(User, UserAdmin)
admin.site.unregister(Group)
admin.site.register(Group, CustomGroupAdmin)