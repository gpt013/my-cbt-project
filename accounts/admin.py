from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User, Group
from django.urls import reverse
from django.utils.html import format_html
# [핵심] 새로 추가된 모델들 import
from .models import (
    Profile, Badge, Company, EvaluationRecord, PartLeader, Process, RecordType, 
    Cohort, EvaluationCategory, EvaluationItem, ManagerEvaluation
)
from quiz.models import Quiz, TestResult

# --- 1. 기본 정보 관리 ---

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
    list_display = ('name', 'email', 'company', 'process')
    list_filter = ('company', 'process') 
    search_fields = ('name', 'email', 'company__name', 'process__name') 
    autocomplete_fields = ('company', 'process') 

@admin.register(Process)
class ProcessAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',) 

@admin.register(RecordType)
class RecordTypeAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)

# --- [신규] 기수(Cohort) 관리 ---
@admin.register(Cohort)
class CohortAdmin(admin.ModelAdmin):
    list_display = ('name', 'start_date', 'end_date', 'is_registration_open')
    list_filter = ('is_registration_open', 'start_date')
    list_editable = ('is_registration_open',) 
    search_fields = ('name',)
    ordering = ('-start_date',)

# --- [신규] 매니저 평가 항목 관리 ---
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
            # is_staff=True인 사용자만 쿼리셋에 포함
            kwargs["queryset"] = User.objects.filter(is_staff=True)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

# --- 2. 'Profile' Admin ---
@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    # [수정] class_number -> get_cohort
    list_display = ('user', 'name', 'company', 'get_cohort', 'get_process_name', 'is_profile_complete')
    
    search_fields = (
        'user__username', 
        'name',           
        'employee_id',    
        'cohort__name',   # [수정] 기수 이름으로 검색
        'process__name',  
        'company__name',  
        'pl__name',       
    )
    
    list_filter = ('is_profile_complete', 'cohort', 'company', 'process')
    autocomplete_fields = ('user', 'company', 'process', 'pl', 'cohort') 
    filter_horizontal = ('badges',)
    
    @admin.display(description='공정', ordering='process__name')
    def get_process_name(self, obj):
        return obj.process.name if obj.process else ''

    @admin.display(description='기수', ordering='cohort__name')
    def get_cohort(self, obj):
        return obj.cohort.name if obj.cohort else ''
    
# --- 3. 'EvaluationRecord' Admin ---
@admin.register(EvaluationRecord)
class EvaluationRecordAdmin(admin.ModelAdmin):
    list_display = ('profile_name', 'get_record_type', 'description_snippet', 'created_at')
    # [수정] profile__cohort 필터 사용
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

# --- 4. '그룹' 관리자 (UserInline) ---
class UserInline(admin.TabularInline):
    model = User.groups.through
    verbose_name = "소속된 교육생"
    verbose_name_plural = "소속된 교육생 목록"
    # [수정] class_number -> get_cohort
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
    
    # [수정] 기수 표시
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

# --- 5. '사용자' 관리자 (UserAdmin) ---
class EvaluationRecordInline(admin.TabularInline):
    model = EvaluationRecord
    extra = 1
    readonly_fields = ('created_at',)
    fields = ('record_type', 'description', 'created_at')
    autocomplete_fields = ('record_type',)

class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    verbose_name_plural = '추가 정보'
    filter_horizontal = ('badges',)
    # [수정] class_number -> cohort
    fields = ('is_profile_complete', 'company', 'name', 'employee_id', 'cohort', 'process', 'line', 'pl', 'badges')
    autocomplete_fields = ('company', 'process', 'pl', 'cohort') 

@admin.action(description='선택된 사용자들을 활성 상태로 변경 (승인)')
def activate_users(modeladmin, request, queryset):
    queryset.update(is_active=True)

class UserAdmin(BaseUserAdmin):
    inlines = (ProfileInline,)
    # [수정] class_number_display -> get_cohort
    list_display = ('username', 'name', 'employee_id', 'get_cohort', 'get_company', 'get_process', 'get_pl', 'is_staff', 'is_active')
    
    # [수정] profile__class_number -> profile__cohort
    list_filter = ('is_active', 'is_staff', 'groups', 'profile__company', 'profile__cohort', 'profile__process', 'profile__pl')
    search_fields = ('username', 'profile__name', 'profile__employee_id')

    ordering = ('-is_staff', 'username')
    actions = [activate_users]
    
    class Media:
        js = ('admin/js/process_handler.js',)
    
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
    
    # [수정] 기수 표시 메서드 변경
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

# --- 6. 최종 등록 ---
admin.site.unregister(User)
admin.site.register(User, UserAdmin)
admin.site.unregister(Group)
admin.site.register(Group, CustomGroupAdmin)