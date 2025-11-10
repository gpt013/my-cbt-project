from django.contrib import admin
from .models import Quiz, Question, Choice, TestResult, UserAnswer, QuizAttempt, Tag, ExamSheet
from django.urls import reverse
from django.utils.html import format_html
from django.db.models import Count
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

# --- 1. 인라인 클래스 정의 ---
class ChoiceInline(admin.TabularInline):
    model = Choice
    extra = 1

class QuestionInline(admin.StackedInline):
    model = Question
    extra = 0
    show_change_link = True
    inlines = [ChoiceInline]

# --- 2. 모델별 관리자 화면 클래스 정의 ---

class ExamSheetAdmin(admin.ModelAdmin):
    list_display = ('name', 'quiz', 'question_count')
    filter_horizontal = ('questions',)
    
    def get_fieldsets(self, request, obj=None):
        if obj:
            return [(None, {'fields': ('quiz', 'name')}), ('문제 선택', {'fields': ('questions',)})]
        return [(None, {'fields': ('quiz', 'name')})]

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == "questions":
            obj_id = request.resolver_match.kwargs.get('object_id')
            if obj_id:
                exam_sheet = self.get_object(request, obj_id)
                kwargs["queryset"] = Question.objects.filter(quiz=exam_sheet.quiz)
            else:
                kwargs["queryset"] = Question.objects.none()
        return super().formfield_for_manytomany(db_field, request, **kwargs)

    def question_count(self, obj):
        return obj.questions.count()
    question_count.short_description = '문제 개수'

class QuizAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'generation_method', 'question_count')
    list_filter = ('generation_method', 'category') 
    filter_horizontal = ('allowed_groups',)
    
    fieldsets = (
        (None, {'fields': ('title', 'category', 'associated_process', 'allowed_groups', 'generation_method', 'exam_sheet')}),
    )
    
    class Media:
        js = ('admin/js/quiz_admin.js',)

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
    # [수정] '대기중'인 것만 골라서 승인합니다.
    queryset_to_approve = queryset.filter(status='대기중')
    queryset_to_approve.update(status='승인됨')
    
    # [수정] 알림 전송 로직
    channel_layer = get_channel_layer()
    if channel_layer:
        for attempt in queryset_to_approve:
            user_id = attempt.user.id
            quiz_title = attempt.quiz.title
            
            async_to_sync(channel_layer.group_send)(
                f'user_{user_id}',
                {
                    'type': 'send_notification',
                    'message': f"'{quiz_title}' 시험 응시가 승인되었습니다! 지금 바로 시작할 수 있습니다."
                }
            )
    # ------------------------------------

class QuizAttemptAdmin(admin.ModelAdmin):
    list_display = ('get_user', 'get_quiz', 'attempt_number', 'status', 'get_requested_at')
    # --- [핵심 수정] 'user' 필터를 다시 추가합니다 ---
    list_filter = ('status', 'quiz', 'user', 'user__profile__class_number', 'user__profile__process')
    list_editable = ('status',)
    actions = [approve_attempts]
    search_fields = ('user__username', 'user__profile__name', 'user__profile__employee_id')

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
    # 'is_pass'를 목록과 필터에 추가
    list_display = ('get_user', 'get_quiz', 'attempt_number', 'score', 'is_pass', 'get_completed_at')
    list_filter = ('is_pass', 'quiz', 'user', 'user__profile__class_number', 'user__profile__process')
    search_fields = ('user__username', 'user__profile__name', 'user__profile__employee_id')

    @admin.display(description='교육생', ordering='user__username')
    def get_user(self, obj):
        return obj.user.username
    @admin.display(description='퀴즈 제목', ordering='quiz__title')
    def get_quiz(self, obj):
        return obj.quiz.title
    @admin.display(description='완료 시간', ordering='completed_at')
    def get_completed_at(self, obj):
        return obj.completed_at.strftime('%Y-%m-%d %H:%M')

class UserAnswerAdmin(admin.ModelAdmin):
    list_display = ('get_question_text', 'get_user', 'is_correct')
    # --- [핵심 수정] 'test_result__user' 필터를 다시 추가합니다 ---
    list_filter = ('is_correct', 'test_result__quiz', 'test_result__user', 'test_result__user__profile__class_number', 'test_result__user__profile__process')
    search_fields = ('test_result__user__username', 'test_result__user__profile__name', 'question__question_text')

    @admin.display(description='문제', ordering='question__question_text')
    def get_question_text(self, obj):
        return obj.question.question_text
    @admin.display(description='교육생', ordering='test_result__user__username')
    def get_user(self, obj):
        return obj.test_result.user.username

# --- 3. 최종 등록 ---
admin.site.register(Quiz, QuizAdmin)
admin.site.register(Question, QuestionAdmin)
admin.site.register(Tag, TagAdmin)
admin.site.register(ExamSheet, ExamSheetAdmin)
admin.site.register(UserAnswer, UserAnswerAdmin)
admin.site.register(TestResult, TestResultAdmin)
admin.site.register(QuizAttempt, QuizAttemptAdmin)

