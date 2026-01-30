from django.contrib import admin
from django import forms
from django.urls import reverse
from django.utils.html import format_html
from django.db.models import Count
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync


# 모델 임포트
from .models import (
    Quiz, Question, Choice, TestResult, UserAnswer, 
    QuizAttempt, Tag, ExamSheet, StudentLog, Room, Reservation, Notification

)

# ------------------------------------------------------------------
# 1. 폼(Forms) 정의 - 유효성 검사 및 커스텀 로직
# ------------------------------------------------------------------
class QuizAdminForm(forms.ModelForm):
    class Meta:
        model = Quiz
        fields = '__all__'

    def clean(self):
        cleaned_data = super().clean()
        category = cleaned_data.get('category')
        related_process = cleaned_data.get('related_process')

        # [안전장치] 분류가 '공정' 또는 'process'인데 관련 공정을 비워둔 경우 에러 발생
        if category in ['공정', 'process'] and not related_process:
            raise forms.ValidationError(
                "분류가 '공정'인 경우, 반드시 '관련 공정'을 선택해야 합니다."
            )
        return cleaned_data


# ------------------------------------------------------------------
# 2. 인라인(Inline) 클래스 - 보기 관리
# ------------------------------------------------------------------
class ChoiceInline(admin.TabularInline):
    model = Choice
    extra = 1
    fields = ('choice_text', 'is_correct', 'image_preview') 
    readonly_fields = ('image_preview',)

    def image_preview(self, obj):
        if obj.image:
            return format_html('<img src="{}" style="max-height: 50px; border-radius: 5px;" />', obj.image.url)
        return "-"
    image_preview.short_description = "이미지 미리보기"

    def get_max_num(self, request, obj=None, **kwargs):
        if obj and obj.question_type == '주관식 (단일정답)':
            return 1
        return None


# ------------------------------------------------------------------
# 3. 모델별 관리자(Admin) 클래스 정의
# ------------------------------------------------------------------

class ExamSheetAdmin(admin.ModelAdmin):
    list_display = ('name', 'quiz', 'question_count_display')
    filter_horizontal = ('questions',)
    search_fields = ('name', 'quiz__title')
    
    def question_count_display(self, obj):
        return obj.questions.count()
    question_count_display.short_description = '포함된 문제 수'


class QuizAdmin(admin.ModelAdmin):
    form = QuizAdminForm
    
    list_display = (
        'title', 'category_badge', 'related_process', 
        'question_count', 'pass_score', 'time_limit', 'created_at'
    )
    list_filter = ('category', 'related_process', 'created_at')
    search_fields = ('title', 'description')
    
    filter_horizontal = ('questions', 'required_tags', 'allowed_groups', 'allowed_users') 
    
    fieldsets = (
        ('기본 정보', {
            'fields': ('title', 'description', ('category', 'related_process'), 'created_by')
        }),
        ('권한 설정', {
            'fields': ('allowed_groups', 'allowed_users'),
            'description': '특정 그룹이나 사용자에게만 시험을 노출하려면 설정하세요.'
        }),
        ('시험 규칙', {
            'fields': (('question_count', 'time_limit', 'pass_score'),),
            'description': '문항 수, 제한 시간(분), 합격 점수를 설정합니다.'
        }),
        ('문제 출제 방식', {
            'fields': ('generation_method', 'required_tags', 'questions'),
            'description': '랜덤 출제 시 태그를 활용하거나, 고정 문제를 지정할 수 있습니다.'
        }),
        ('구버전 호환', {
            'fields': ('exam_sheet',),
            'classes': ('collapse',),
        }),
    )

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def category_badge(self, obj):
        colors = {'공통': 'gray', 'common': 'gray', '공정': 'blue', 'process': 'blue', '안전': 'green'}
        color = colors.get(obj.category, 'black')
        return format_html(
            '<span style="color: white; background-color: {}; padding: 3px 7px; border-radius: 5px;">{}</span>',
            color, obj.get_category_display()
        )
    category_badge.short_description = "분류"


class QuestionAdmin(admin.ModelAdmin):
    list_display = ('question_text_short', 'question_type', 'difficulty', 'image_icon', 'created_at')
    list_filter = ('question_type', 'difficulty', 'tags')
    search_fields = ('question_text',)
    inlines = [ChoiceInline]
    filter_horizontal = ('tags',)

    def question_text_short(self, obj):
        return obj.question_text[:40] + "..." if len(obj.question_text) > 40 else obj.question_text
    question_text_short.short_description = "질문 내용"

    def image_icon(self, obj):
        if obj.image:
            return format_html('<i class="bi bi-image" title="이미지 있음"></i> 📷')
        return ""
    image_icon.short_description = "이미지"


class TagAdmin(admin.ModelAdmin):
    list_display = ('name', 'view_questions_link', 'count_questions')
    search_fields = ('name',)
    
    def view_questions_link(self, obj):
        url = reverse('admin:quiz_question_changelist') + f'?tags__id__exact={obj.id}'
        return format_html('<a href="{}">문제 보기</a>', url)
    view_questions_link.short_description = '연결된 문제'

    def count_questions(self, obj):
        return obj.question_set.count()
    count_questions.short_description = '문제 개수'


# --- 커스텀 액션: 승인 및 알림 ---
@admin.action(description='✅ 선택된 요청 승인 및 알림 발송')
def approve_attempts(modeladmin, request, queryset):
    queryset_to_approve = queryset.filter(status='대기중')
    count = queryset_to_approve.count()
    
    queryset_to_approve.update(status='승인됨')
    
    channel_layer = get_channel_layer()
    if channel_layer:
        for attempt in queryset_to_approve:
            try:
                user_id = attempt.user.id
                quiz_title = attempt.quiz.title
                async_to_sync(channel_layer.group_send)(
                    f'user_{user_id}',
                    {
                        'type': 'send_notification',
                        'message': f"🔔 '{quiz_title}' 시험 응시가 승인되었습니다!"
                    }
                )
            except Exception as e:
                print(f"알림 발송 실패 (User {attempt.user.id}): {e}")

    modeladmin.message_user(request, f"{count}건의 요청을 승인했습니다.")


class QuizAttemptAdmin(admin.ModelAdmin):
    # [수정] list_editable에 'status'가 있으므로, list_display에도 반드시 'status'가 있어야 합니다.
    # 기존 'status_badge' 대신 실제 필드인 'status'를 사용합니다.
    list_display = ('get_user_info', 'get_quiz_title', 'attempt_number', 'status', 'requested_at')
    
    list_filter = ('status', 'quiz', 'user__profile__cohort', 'user__profile__process')
    
    # 목록에서 바로 상태 변경 가능
    list_editable = ('status',)
    
    actions = [approve_attempts]
    search_fields = ('user__username', 'user__profile__name')

    def get_user_info(self, obj):
        if hasattr(obj.user, 'profile'):
            return f"{obj.user.profile.name} ({obj.user.profile.employee_id})"
        return obj.user.username
    get_user_info.short_description = '교육생'

    def get_quiz_title(self, obj):
        return obj.quiz.title
    get_quiz_title.short_description = '퀴즈 제목'


class TestResultAdmin(admin.ModelAdmin):
    list_display = ('get_user', 'get_process', 'get_quiz', 'score', 'is_pass_icon', 'completed_at')
    list_filter = ('is_pass', 'quiz', 'user__profile__process', 'user__profile__cohort')
    search_fields = ('user__username', 'user__profile__name', 'quiz__title')

    def get_user(self, obj):
        return obj.user.profile.name if hasattr(obj.user, 'profile') else obj.user.username
    get_user.short_description = '이름'

    def get_process(self, obj):
        return obj.user.profile.process.name if hasattr(obj.user, 'profile') and obj.user.profile.process else '-'
    get_process.short_description = '공정'

    def get_quiz(self, obj):
        return obj.quiz.title
    get_quiz.short_description = '시험 제목'

    def is_pass_icon(self, obj):
        return "✅ 합격" if obj.is_pass else "❌ 불합격"
    is_pass_icon.short_description = "결과"


class UserAnswerAdmin(admin.ModelAdmin):
    list_display = ('get_short_question', 'get_user', 'get_result', 'is_correct_icon')
    list_filter = ('is_correct', 'test_result__quiz')
    search_fields = ('question__question_text', 'test_result__user__username')

    def get_short_question(self, obj):
        return obj.question.question_text[:30] + "..."
    get_short_question.short_description = "문제"

    def get_user(self, obj):
        return obj.test_result.user.username
    get_user.short_description = "응시자"

    def get_result(self, obj):
        answer = obj.selected_choice.choice_text if obj.selected_choice else obj.short_answer_text
        return answer
    get_result.short_description = "제출 답안"

    def is_correct_icon(self, obj):
        return "🟢" if obj.is_correct else "🔴"
    is_correct_icon.short_description = "정답여부"


class StudentLogAdmin(admin.ModelAdmin):
    list_display = ('log_type_badge', 'get_student_name', 'reason_short', 'created_at', 'is_resolved')
    list_filter = ('log_type', 'is_resolved', 'created_at')
    search_fields = ('profile__name', 'reason')
    list_editable = ('is_resolved',)

    def log_type_badge(self, obj):
        return f"{obj.get_log_type_display()}"
    log_type_badge.short_description = "유형"

    def get_student_name(self, obj):
        return f"{obj.profile.name} ({obj.profile.process})"
    get_student_name.short_description = "대상 학생"

    def reason_short(self, obj):
        return obj.reason[:30] + "..." if len(obj.reason) > 30 else obj.reason
    reason_short.short_description = "내용"

# 강의실 관리
@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ('name', 'room_type', 'target_process', 'capacity', 'is_active')
    list_filter = ('room_type', 'target_process')
    # ★ 관리자를 체크박스로 편하게 고르기 위해 추가
    filter_horizontal = ('managers',)

# 예약 관리
@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = ('title', 'room', 'user', 'start_time', 'status')
    list_filter = ('status', 'start_time', 'room')
    search_fields = ('title', 'user__username')

# ------------------------------------------------------------------
# 4. 최종 등록 (중복 방지)
# ------------------------------------------------------------------
admin.site.register(Quiz, QuizAdmin)
admin.site.register(Question, QuestionAdmin)
admin.site.register(Choice)
admin.site.register(Tag, TagAdmin)
admin.site.register(ExamSheet, ExamSheetAdmin)
admin.site.register(UserAnswer, UserAnswerAdmin)
admin.site.register(TestResult, TestResultAdmin)
admin.site.register(QuizAttempt, QuizAttemptAdmin)
admin.site.register(StudentLog, StudentLogAdmin)
admin.site.register(Notification)