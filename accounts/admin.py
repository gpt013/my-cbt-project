from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User, Group
from django.urls import reverse
from django.utils.html import format_html
from .models import Profile, Badge, Company, EvaluationRecord, PartLeader, Process, RecordType
from quiz.models import Quiz, TestResult

# --- 1. [순서 수정] 'autocomplete'의 대상이 되는 기본 Admin들을 먼저 정의합니다 ---

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
    list_filter = ('company',)
    search_fields = ('name', 'email') 

@admin.register(Process)
class ProcessAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',) 

@admin.register(RecordType)
class RecordTypeAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)

# --- 2. 'Profile' Admin 정의 (EvaluationRecord가 참조해야 하므로 먼저 정의) ---
# [핵심] Profile을 '사용자' 메뉴의 Inline과 별개로, 검색/참조용으로 등록합니다.
@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'name', 'company', 'class_number', 'get_process_name')
    
    # --- [핵심 수정] '필터'와 '검색' 요청을 위해 검색 필드를 대폭 강화합니다 ---
    search_fields = (
        'user__username', # 사용자 ID
        'name',           # 이름
        'employee_id',    # 사번
        'class_number',   # 기수
        'process__name',  # 공정 이름
        'company__name',  # 회사 이름
        'pl__name',       # PL 이름
    )
    
    autocomplete_fields = ('user', 'company', 'process', 'pl')
    filter_horizontal = ('badges',)
    
    @admin.display(description='공정', ordering='process__name')
    def get_process_name(self, obj):
        return obj.process.name if obj.process else ''
    
# --- 3. 'EvaluationRecord' Admin 정의 (중복 제거) ---
# [핵심 수정] 팝업(raw_id_fields) 대신 '내부 검색(autocomplete_fields)' 사용
@admin.register(EvaluationRecord)
class EvaluationRecordAdmin(admin.ModelAdmin):
    list_display = ('profile_name', 'get_record_type', 'description_snippet', 'created_at')
    list_filter = ('record_type', 'profile__company', 'profile__class_number', 'profile__process', 'profile__pl')
    search_fields = ('profile__user__username', 'profile__name', 'description')
    
    autocomplete_fields = ('profile',) # '내부 검색' 사용

    @admin.display(description='교육생 이름', ordering='profile__name')
    def profile_name(self, obj):
        return obj.profile.name
    
    @admin.display(description='기록 유형', ordering='record_type__name')
    def get_record_type(self, obj):
        return obj.record_type.name if obj.record_type else ''

    @admin.display(description='세부 내용')
    def description_snippet(self, obj):
        return obj.description[:30] + "..." if len(obj.description) > 30 else obj.description

# --- 4. '그룹' 관리자 (모든 프로필 정보 표시 - 누락 없음) ---
class UserInline(admin.TabularInline):
    model = User.groups.through
    verbose_name = "소속된 교육생"
    verbose_name_plural = "소속된 교육생 목록"
    readonly_fields = ('user_link', 'name', 'employee_id', 'class_number', 'get_company', 'process', 'get_pl', 'first_attempt_scores')
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
    def class_number(self, instance):
        num = instance.user.profile.class_number if hasattr(instance.user, 'profile') else ''
        return f"{num}기" if num else ''
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

# --- 5. '사용자' 관리자 (최종) ---
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
    fields = ('company', 'name', 'employee_id', 'class_number', 'process', 'line', 'pl', 'badges')
    inlines = [EvaluationRecordInline]
    autocomplete_fields = ('company', 'process', 'pl') 

@admin.action(description='선택된 사용자들을 활성 상태로 변경 (승인)')
def activate_users(modeladmin, request, queryset):
    queryset.update(is_active=True)

class UserAdmin(BaseUserAdmin):
    inlines = (ProfileInline,)
    list_display = ('username', 'name', 'employee_id', 'class_number_display', 'get_company', 'get_process', 'get_pl', 'is_staff', 'is_active')
    
    # --- [핵심] '필터' 및 '검색' 기능 (요청하신 사항) ---
    list_filter = ('is_active', 'is_staff', 'groups', 'profile__company', 'profile__class_number', 'profile__process', 'profile__pl')
    search_fields = ('username', 'profile__name', 'profile__employee_id')
    # -----------------------------------------------

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
    def class_number_display(self, obj):
        if hasattr(obj, 'profile') and obj.profile.class_number:
            return f"{obj.profile.class_number}기"
        return ''
    class_number_display.short_description = '기수'
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