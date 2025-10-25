from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.contrib import admin
from .models import Quiz, Question, Choice, TestResult, UserAnswer, QuizAttempt, Tag, ExamSheet
from django.urls import reverse
from django.utils.html import format_html
from django.db.models import Count


# --- 1. 인라인 클래스 정의 ---
class ChoiceInline(admin.TabularInline):
    model = Choice
    extra = 1

class QuestionInline(admin.StackedInline):
    model = Question
    extra = 0
    show_change_link = True
    inlines = [ChoiceInline]

class ExamSheetAdmin(admin.ModelAdmin):
    list_display = ('name', 'quiz', 'question_count')
    filter_horizontal = ('questions',)

    # --- [핵심] '관련 퀴즈'를 선택해야만 '문제' 필드가 나타나도록 합니다 ---
    def get_fieldsets(self, request, obj=None):
        fieldsets = [
            (None, {'fields': ('quiz', 'name')}),
        ]
        if obj: # 이미 저장된 객체일 경우에만 'questions' 필드를 보여줌
            fieldsets.append(('문제 선택', {'fields': ('questions',)}))
        return fieldsets

    # '문제' 선택 목록에 '관련 퀴즈'의 문제들만 나타나도록 필터링합니다.
    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == "questions":
            # 현재 편집중인 ExamSheet 객체의 quiz_id를 가져옵니다.
            obj_id = request.resolver_match.kwargs.get('object_id')
            if obj_id:
                exam_sheet = self.get_object(request, obj_id)
                kwargs["queryset"] = Question.objects.filter(quiz=exam_sheet.quiz)
            else:
                kwargs["queryset"] = Question.objects.none() # 새로 만들 때는 빈 목록
        return super().formfield_for_manytomany(db_field, request, **kwargs)

    def question_count(self, obj):
        return obj.questions.count()
    question_count.short_description = '문제 개수'

class QuizAdmin(admin.ModelAdmin):
    list_display = ('title', 'question_count', 'generation_method')
    list_filter = ('generation_method',)
    filter_horizontal = ('allowed_groups',)
    fieldsets = (
        (None, {'fields': ('title', 'allowed_groups', 'generation_method', 'exam_sheet')}),
    )
    
    class Media:
        js = ('admin/js/quiz_admin.js',)

    # [핵심] '문제 세트' 선택 목록을 현재 퀴즈에 맞게 필터링합니다.
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "exam_sheet":
            obj_id = request.resolver_match.kwargs.get('object_id')
            if obj_id:
                kwargs["queryset"] = ExamSheet.objects.filter(quiz_id=obj_id)
            else:
                kwargs["queryset"] = ExamSheet.objects.none()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def question_count(self, obj):
        return obj.question_set.count()
    question_count.short_description = '문제 개수'

class QuestionAdmin(admin.ModelAdmin):
    list_display = ('question_text', 'quiz', 'question_type', 'difficulty')
    list_filter = ('quiz', 'question_type', 'difficulty', 'tags')
    inlines = [ChoiceInline]
    filter_horizontal = ('tags',)
    search_fields = ('question_text',)

class TagAdmin(admin.ModelAdmin):
    list_display = ('view_questions_link', 'question_count')
    def view_questions_link(self, obj):
        url = reverse('admin:quiz_question_changelist') + f'?tags__id__exact={obj.id}'
        return format_html('<a href="{}">{}</a>', url, obj.name)
    view_questions_link.short_description = '태그 이름 (클릭하여 문제 보기)'
    def question_count(self, obj):
        return obj.question_set.count()
    question_count.short_description = '연결된 문제 개수'

@admin.action(description='선택된 요청을 승인함')
def approve_attempts(modeladmin, request, queryset):
    # 1. 먼저 상태를 '승인됨'으로 변경합니다.
    queryset.update(status='승인됨')

    # --- [핵심 추가] 알림을 보내는 로직 ---
    channel_layer = get_channel_layer()
    # 승인된 각 요청에 대해 반복합니다.
    for attempt in queryset:
        user_id = attempt.user.id
        quiz_title = attempt.quiz.title

        # 해당 사용자의 개인 채널 그룹으로 메시지를 보냅니다.
        async_to_sync(channel_layer.group_send)(
            f'user_{user_id}', # 예: 'user_1', 'user_2'
            {
                'type': 'send_notification', # consumers.py의 함수 이름
                'message': f"'{quiz_title}' 시험 응시가 승인되었습니다! 지금 바로 시작할 수 있습니다."
            }
        )

class QuizAttemptAdmin(admin.ModelAdmin):
    list_display = ('get_user', 'get_quiz', 'attempt_number', 'status', 'get_requested_at')
    list_filter = ('status', 'quiz', 'user')
    list_editable = ('status',)
    actions = [approve_attempts]

    @admin.display(description='교육생', ordering='user__username')
    def get_user(self, obj):
        return obj.user.username

    @admin.display(description='퀴즈 제목', ordering='quiz__title')
    def get_quiz(self, obj):
        return obj.quiz.title

    @admin.display(description='요청 시간', ordering='requested_at')
    def get_requested_at(self, obj):
        return obj.requested_at.strftime('%Y-%m-%d %H:%M')

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.status == '완료됨':
            return [field.name for field in obj._meta.fields]
        return []

class TestResultAdmin(admin.ModelAdmin):
    list_display = ('user', 'quiz', 'attempt_number', 'score', 'completed_at')
    list_filter = ('quiz', 'user')

class UserAnswerAdmin(admin.ModelAdmin):
    list_display = ('test_result', 'question', 'selected_choice', 'is_correct')
    list_filter = ('test_result', 'is_correct')

# --- 3. 최종 등록 ---
admin.site.register(Quiz, QuizAdmin)
admin.site.register(Question, QuestionAdmin)
admin.site.register(Tag, TagAdmin)
admin.site.register(UserAnswer, UserAnswerAdmin)
admin.site.register(TestResult, TestResultAdmin)
admin.site.register(QuizAttempt, QuizAttemptAdmin)
admin.site.register(ExamSheet, ExamSheetAdmin)