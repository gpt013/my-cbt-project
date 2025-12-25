from django.contrib import admin
from .models import Quiz, Question, Choice, TestResult, UserAnswer, QuizAttempt, Tag, ExamSheet,StudentLog
from django.urls import reverse
from django.utils.html import format_html
from django.db.models import Count
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

# --- 1. 인라인 클래스 정의 ---

class ChoiceInline(admin.TabularInline):
    model = Choice
    extra = 1

    def get_max_num(self, request, obj=None, **kwargs):
        """ 
        질문 객체(obj)의 유형에 따라 최대 보기/정답 개수를 동적으로 조절합니다.
        """
        if obj:
            if obj.question_type == '주관식 (단일정답)':
                return 1
        return None

# (QuestionInline은 Question이 Quiz에 종속되지 않게 바뀌었으므로 삭제되었습니다. 
#  대신 QuizAdmin에서 questions M2M 필드로 관리합니다.)


# --- 2. 모델별 관리자 화면 클래스 정의 ---

class ExamSheetAdmin(admin.ModelAdmin):
    list_display = ('name', 'quiz', 'question_count')
    # [수정] ExamSheet도 독립적인 문제 구성을 가질 수 있도록 수정
    filter_horizontal = ('questions',) 
    
    def question_count(self, obj):
        return obj.questions.count()
    question_count.short_description = '문제 개수'


class QuizAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'generation_method', 'associated_process', 'question_count')
    list_filter = ('generation_method', 'category', 'associated_process') 
    
    # [핵심] questions(문제은행), required_tags, allowed_xxx 등 M2M 필드 관리
    filter_horizontal = ('questions', 'required_tags', 'allowed_groups', 'allowed_users')
    
    fieldsets = (
        ('기본 정보', {
            'fields': ('title', 'category', 'associated_process')
        }),
        ('응시 권한 설정 (그룹 또는 개인)', {
            'fields': ('allowed_groups', 'allowed_users'),
            'description': '그룹에 속해있거나, 개별 인원으로 지정된 사람은 시험을 볼 수 있습니다.'
        }),
        ('문제 출제 설정', {
            'fields': ('generation_method', 'required_tags', 'questions'),
            'description': "랜덤 출제 시 '태그', 지정 출제 시 '포함된 문제들(Questions)'을 선택하세요."
        }),
    )
    
    # 구버전 ExamSheet 호환 (필요 시 주석 해제)
    # def formfield_for_foreignkey ... (생략: 새 구조에서는 questions M2M 직접 사용 권장)

    def question_count(self, obj):
        # M2M 필드 카운트
        return obj.questions.count()
    question_count.short_description = '지정 문제 수'


class QuestionAdmin(admin.ModelAdmin):
    # [수정] 'quiz' 필드가 삭제되었으므로 list_display 및 list_filter에서 제거
    list_display = ('question_text', 'question_type', 'difficulty', 'created_at')
    list_filter = ('question_type', 'difficulty', 'tags')
    inlines = [ChoiceInline]
    filter_horizontal = ('tags',)
    search_fields = ('question_text',)


class TagAdmin(admin.ModelAdmin):
    list_display = ('name', 'view_questions_link', 'question_count')
    
    def view_questions_link(self, obj):
        # 태그 클릭 시 해당 태그를 가진 문제 목록으로 이동
        url = reverse('admin:quiz_question_changelist') + f'?tags__id__exact={obj.id}'
        return format_html('<a href="{}">{}</a>', url, obj.name)
    view_questions_link.short_description = '태그 이름 (필터링)'

    def question_count(self, obj):
        return obj.question_set.count()
    question_count.short_description = '연결된 문제 개수'


# --- 3. 커스텀 액션 ---

@admin.action(description='✅ 선택된 요청 승인 및 알림 발송')
def approve_attempts(modeladmin, request, queryset):
    queryset_to_approve = queryset.filter(status='대기중')
    count = queryset_to_approve.count()
    queryset_to_approve.update(status='승인됨')
    
    # 채널스(Websocket) 알림 발송
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
    modeladmin.message_user(request, f"{count}건의 요청을 승인했습니다.")


class QuizAttemptAdmin(admin.ModelAdmin):
    list_display = ('get_user', 'get_quiz', 'attempt_number', 'status', 'get_requested_at')
    
    # [핵심] 필터링 (기수, 공정, 상태 등)
    list_filter = ('status', 'quiz', 'user', 'user__profile__cohort', 'user__profile__process')
    
    list_editable = ('status',)
    actions = [approve_attempts]
    search_fields = ('user__username', 'user__profile__name', 'user__profile__employee_id')

    @admin.display(description='교육생', ordering='user__username')
    def get_user(self, obj):
        return f"{obj.user.profile.name} ({obj.user.username})"

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
    list_display = ('get_user_name', 'get_cohort', 'get_process', 'get_quiz', 'score', 'is_pass', 'get_completed_at')
    list_filter = ('is_pass', 'quiz', 'user__profile__cohort', 'user__profile__process')
    
    search_fields = (
        'user__username',             # 아이디
        'user__profile__name',        # 실명
        'user__profile__employee_id', # 사번
        'user__profile__cohort__name',
        'user__profile__process__name'
    )

    @admin.display(description='이름', ordering='user__profile__name')
    def get_user_name(self, obj):
        return obj.user.profile.name if hasattr(obj.user, 'profile') else obj.user.username

    @admin.display(description='기수', ordering='user__profile__cohort__name')
    def get_cohort(self, obj):
        return obj.user.profile.cohort.name if hasattr(obj.user, 'profile') and obj.user.profile.cohort else '-'

    @admin.display(description='공정', ordering='user__profile__process__name')
    def get_process(self, obj):
        return obj.user.profile.process.name if hasattr(obj.user, 'profile') and obj.user.profile.process else '-'

    @admin.display(description='퀴즈 제목', ordering='quiz__title')
    def get_quiz(self, obj):
        return obj.quiz.title

    @admin.display(description='완료 시간', ordering='completed_at')
    def get_completed_at(self, obj):
        return obj.completed_at.strftime('%Y-%m-%d %H:%M')


class UserAnswerAdmin(admin.ModelAdmin):
    list_display = ('get_question_text', 'get_user', 'is_correct')
    list_filter = ('is_correct', 'test_result__quiz', 'test_result__user__profile__cohort', 'test_result__user__profile__process')
    search_fields = ('test_result__user__username', 'test_result__user__profile__name', 'question__question_text')

    @admin.display(description='문제', ordering='question__question_text')
    def get_question_text(self, obj):
        return obj.question.question_text[:50]
    
    @admin.display(description='교육생', ordering='test_result__user__username')
    def get_user(self, obj):
        return obj.test_result.user.username
    
@admin.register(StudentLog)
class StudentLogAdmin(admin.ModelAdmin):
    list_display = ('get_type_display', 'profile', 'reason', 'created_by', 'created_at', 'is_resolved')
    list_filter = ('log_type', 'is_resolved', 'created_at')
    search_fields = ('profile__name', 'reason')
    
    def get_type_display(self, obj):
        return obj.get_log_type_display()
    get_type_display.short_description = '유형'


# --- 4. 최종 등록 ---
admin.site.register(Quiz, QuizAdmin)
admin.site.register(Question, QuestionAdmin)
admin.site.register(Tag, TagAdmin)
admin.site.register(ExamSheet, ExamSheetAdmin)
admin.site.register(UserAnswer, UserAnswerAdmin)
admin.site.register(TestResult, TestResultAdmin)
admin.site.register(QuizAttempt, QuizAttemptAdmin)