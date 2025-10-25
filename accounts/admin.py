# accounts/admin.py (최종 완성본)

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User, Group
from django.urls import reverse
from django.utils.html import format_html
from .models import Profile, Badge
from quiz.models import Quiz, TestResult


# '일괄 승인' 액션
@admin.action(description='선택된 사용자들을 활성 상태로 변경 (승인)')
def activate_users(modeladmin, request, queryset):
    queryset.update(is_active=True)

class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    verbose_name_plural = '추가 정보'
    # --- 뱃지 선택 위젯을 추가합니다 ---
    filter_horizontal = ('badges',)

# 그룹 화면에 보여줄 읽기 전용 사용자 목록
class UserInline(admin.TabularInline):
    model = User.groups.through
    verbose_name = "소속된 교육생"
    verbose_name_plural = "소속된 교육생 목록"
    readonly_fields = ('user_link', 'name', 'employee_id', 'class_number', 'process', 'pl_name', 'first_attempt_scores')
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

    @admin.display(description='공정')
    def process(self, instance):
        return instance.user.profile.process if hasattr(instance.user, 'profile') else ''
        
    @admin.display(description='PL님 성함')
    def pl_name(self, instance):
        return instance.user.profile.pl_name if hasattr(instance.user, 'profile') else ''
    
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

# Django 기본 그룹 관리자 화면 재정의
class CustomGroupAdmin(admin.ModelAdmin):
    exclude = ('permissions',)
    inlines = [UserInline]
    list_display = ['name']
    search_fields = ['name']

# Profile 모델을 User 편집 화면에 포함
class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    verbose_name_plural = '추가 정보'

# User 관리자 화면 최종 개편
class UserAdmin(BaseUserAdmin):
    inlines = (ProfileInline,)
    list_display = ('username', 'name', 'employee_id', 'class_number_display', 'is_staff', 'is_active')
    list_filter = ('is_active', 'is_staff', 'groups')
    ordering = ('-is_staff', 'username')
    actions = [activate_users]
    
    class Media:
        js = ('admin/js/process_handler.js',)
    
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

# 최종 등록
admin.site.register(Badge)
admin.site.unregister(User)
admin.site.register(User, UserAdmin)
admin.site.unregister(Group)
admin.site.register(Group, CustomGroupAdmin)