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

    def get_max_num(self, request, obj=None, **kwargs):
        """ 
        질문 객체(obj)의 유형에 따라 최대 보기/정답 개수를 동적으로 조절합니다.
        """
        if obj:
            # '주관식 (단일정답)' 유형일 때만
            if obj.question_type == '주관식 (단일정답)':
                return 1
        return None

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
    filter_horizontal = ('allowed_groups', 'allowed_users', 'required_tags')
    
    fieldsets = (
        ('기본 정보', {
            'fields': ('title', 'category', 'associated_process')
        }),
        ('응시 권한 설정 (그룹 또는 개인)', {
            'fields': ('allowed_groups', 'allowed_users'),
            'description': '그룹에 속해있거나, 개별 인원으로 지정된 사람은 시험을 볼 수 있습니다.'
        }),
        ('문제 출제 설정', {
            'fields': ('generation_method', 'exam_sheet', 'required_tags'),
            'description': "출제 방식에 따라 '문제 세트' 또는 '출제 포함 태그'를 선택해주세요."
        }),
    )
    
    class Media:
        js = (
            'admin/js/quiz_admin.js', # (이건 기존에 있던 파일이면 유지)
            'admin/js/quiz_form.js',  # [추가] 방금 만든 동적 화면 제어 스크립트
        )

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
    queryset_to_approve = queryset.filter(status='대기중')
    queryset_to_approve.update(status='승인됨')
    
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

class QuizAttemptAdmin(admin.ModelAdmin):
    list_display = ('get_user', 'get_quiz', 'attempt_number', 'status', 'get_requested_at')
    
    # --- [핵심 수정] class_number -> cohort ---
    list_filter = ('status', 'quiz', 'user', 'user__profile__cohort', 'user__profile__process')
    # -----------------------------------------
    
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
    # 1. [수정] 목록에 '이름', '기수', '공정'이 바로 보이도록 칼럼 추가
    list_display = ('get_user_name', 'get_cohort', 'get_process', 'get_quiz', 'score', 'is_pass', 'get_completed_at')
    
    # 2. [수정] 필터 기능 (오른쪽 사이드바에서 클릭해서 모아보기)
    list_filter = ('is_pass', 'quiz', 'user__profile__cohort', 'user__profile__process')
    
    # 3. [수정] 검색 기능 강화 (이름, 사번, 기수명, 공정명으로 검색 가능)
    search_fields = (
        'user__username',               # 아이디
        'user__profile__name',          # 실명
        'user__profile__employee_id',   # 사번
        'user__profile__cohort__name',  # 기수 이름 (예: 1기)
        'user__profile__process__name'  # 공정 이름 (예: 용접)
    )

    # --- 아래는 화면 표시를 위한 함수들입니다 ---

    @admin.display(description='이름', ordering='user__profile__name')
    def get_user_name(self, obj):
        # 프로필이 있으면 실명을, 없으면 아이디를 표시
        return obj.user.profile.name if hasattr(obj.user, 'profile') else obj.user.username

    @admin.display(description='기수', ordering='user__profile__cohort__name')
    def get_cohort(self, obj):
        if hasattr(obj.user, 'profile') and obj.user.profile.cohort:
            return obj.user.profile.cohort.name
        return '-'

    @admin.display(description='공정', ordering='user__profile__process__name')
    def get_process(self, obj):
        if hasattr(obj.user, 'profile') and obj.user.profile.process:
            return obj.user.profile.process.name
        return '-'

    @admin.display(description='퀴즈 제목', ordering='quiz__title')
    def get_quiz(self, obj):
        return obj.quiz.title

    @admin.display(description='완료 시간', ordering='completed_at')
    def get_completed_at(self, obj):
        return obj.completed_at.strftime('%Y-%m-%d %H:%M')

class UserAnswerAdmin(admin.ModelAdmin):
    list_display = ('get_question_text', 'get_user', 'is_correct')
    
    # --- [핵심 수정] class_number -> cohort ---
    list_filter = ('is_correct', 'test_result__quiz', 'test_result__user', 'test_result__user__profile__cohort', 'test_result__user__profile__process')
    # -----------------------------------------
    
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