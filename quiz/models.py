from django.db import models
from django.contrib.auth.models import User, Group
from accounts.models import Process
from django.conf import settings

# ------------------------------------------------------------------
# 1. 태그 모델 (문제 분류용)
# ------------------------------------------------------------------
class Tag(models.Model):
    name = models.CharField(max_length=50, unique=True, verbose_name='태그 이름')

    class Meta:
        verbose_name = '태그'
        verbose_name_plural = '태그'

    def __str__(self):
        return self.name


# ------------------------------------------------------------------
# 2. 문제(Question) 모델 - [핵심 수정: 독립된 문제 은행]
# ------------------------------------------------------------------
class Question(models.Model):
    class QuestionType(models.TextChoices):
        SINGLE_CHOICE = '객관식'
        MULTIPLE_CHOICE = '다중선택'
        SHORT_ANSWER = '주관식 (단일정답)'
        SHORT_ANSWER_MULTIPLE = '주관식 (복수정답)'

    class Difficulty(models.TextChoices):
        EASY = '하'
        MEDIUM = '중'
        HARD = '상'

    # [삭제됨] quiz = models.ForeignKey(...) <- 이제 문제는 특정 시험에 종속되지 않음!
    
    question_text = models.TextField(verbose_name="문제 내용")
    question_type = models.CharField(
        max_length=20,
        choices=QuestionType.choices,
        default=QuestionType.SINGLE_CHOICE,
        verbose_name="문제 유형"
    )
    difficulty = models.CharField(
        max_length=2,
        choices=Difficulty.choices,
        default=Difficulty.EASY,
        verbose_name="난이도"
    )
    image = models.ImageField(
        upload_to='quiz_images/', 
        blank=True, null=True, 
        verbose_name="이미지"
    )
    tags = models.ManyToManyField(Tag, blank=True, verbose_name='태그')
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = '문제 (Question Bank)'
        verbose_name_plural = '문제 (Question Bank)'

    def __str__(self):
        if len(self.question_text) > 50:
            return self.question_text[:50] + "..."
        return self.question_text


# ------------------------------------------------------------------
# 3. 보기(Choice) 모델
# ------------------------------------------------------------------
class Choice(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='choice_set')
    choice_text = models.CharField(max_length=200, blank=True)
    is_correct = models.BooleanField(default=False)
    image = models.ImageField(upload_to='choice_images/', blank=True, null=True)

    class Meta:
        verbose_name = '보기'
        verbose_name_plural = '보기'

    def __str__(self):
        return self.choice_text


# ------------------------------------------------------------------
# 4. 시험지 세트 (ExamSheet) - [하위 호환성 유지]
# ------------------------------------------------------------------
class ExamSheet(models.Model):
    # Quiz가 아직 정의되지 않았으므로 문자열 참조 'Quiz' 사용
    quiz = models.ForeignKey('Quiz', on_delete=models.CASCADE, verbose_name="관련 퀴즈")
    name = models.CharField(max_length=100, verbose_name="문제 세트 이름")
    questions = models.ManyToManyField(Question, verbose_name="포함된 문제들")

    class Meta:
        verbose_name = '문제 세트'
        verbose_name_plural = '퀴즈 관리 / 5. 문제 세트'

    def __str__(self):
        return f"{self.quiz.title} - {self.name}"


# ------------------------------------------------------------------
# 5. 퀴즈(Quiz) 모델 - [핵심 수정: M2M 필드 추가]
# ------------------------------------------------------------------
class Quiz(models.Model):
    class Category(models.TextChoices):
        COMMON = '공통', '공통 (모든 교육생에게 표시)'
        PROCESS = '공정', '공정 (해당 공정 교육생에게 우선 표시)'

    class GenerationMethod(models.TextChoices):
        RANDOM = '랜덤', '난이도별 랜덤 출제 (기본)'
        FIXED = '지정', '지정 문제 세트 출제' # [수정] ExamSheet 대신 questions M2M 사용
        TAG_RANDOM = '태그', '태그 조합 랜덤 출제'

    title = models.CharField(max_length=200, verbose_name="퀴즈 제목")
    
    # 1. 권한 설정
    allowed_groups = models.ManyToManyField(Group, blank=True, verbose_name='응시 가능 그룹')
    allowed_users = models.ManyToManyField(
        User, blank=True, verbose_name="개별 응시 허용 인원", related_name='allowed_quizzes'
    )

    # 2. 분류 및 방식
    category = models.CharField(
        max_length=10, choices=Category.choices, default=Category.COMMON, verbose_name="퀴즈 분류"
    )
    associated_process = models.ForeignKey(
        Process, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="관련 공정"
    )
    generation_method = models.CharField(
        max_length=10, choices=GenerationMethod.choices, default=GenerationMethod.RANDOM, verbose_name="문제 출제 방식"
    )

    # [핵심 추가] 문제 은행 연결 (다대다 관계) -> 하이브리드 방식 구현의 핵심
    questions = models.ManyToManyField(
        Question, blank=True, related_name='quizzes', verbose_name="포함된 문제들 (지정 방식용)"
    )

    # 태그 방식용
    required_tags = models.ManyToManyField(
        Tag, blank=True, verbose_name="출제 포함 태그"
    )
    
    # (구버전 호환용) ExamSheet 연결 - 필요 없다면 나중에 삭제 가능
    exam_sheet = models.ForeignKey(
        ExamSheet, on_delete=models.SET_NULL, null=True, blank=True, 
        verbose_name="선택된 문제 세트 (구버전)", related_name='+' 
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = '퀴즈'
        verbose_name_plural = '퀴즈'

    def __str__(self):
        return self.title


# ------------------------------------------------------------------
# 6. 응시 기록 (QuizAttempt)
# ------------------------------------------------------------------
class QuizAttempt(models.Model):
    class Status(models.TextChoices):
        PENDING = '대기중'
        APPROVED = '승인됨'
        COMPLETED = '완료됨'

    class AssignmentType(models.TextChoices):
        INDIVIDUAL = '개인 요청'
        GROUP = '그룹 배정'

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    assignment_type = models.CharField(max_length=10, choices=AssignmentType.choices, default=AssignmentType.INDIVIDUAL)
    requested_at = models.DateTimeField(auto_now_add=True)
    attempt_number = models.IntegerField(default=0)

    def save(self, *args, **kwargs):
        if self.pk is None:
            previous_attempts = QuizAttempt.objects.filter(user=self.user, quiz=self.quiz).count()
            self.attempt_number = previous_attempts + 1
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = '응시 요청'
        verbose_name_plural = '응시 요청'

    def __str__(self):
        return f"{self.user.username}의 '{self.quiz.title}' {self.attempt_number}차 요청 ({self.status})"
    
    started_at = models.DateTimeField(auto_now_add=True)

    completed_at = models.DateTimeField(null=True, blank=True)


# ------------------------------------------------------------------
# 7. 시험 결과 (TestResult)
# ------------------------------------------------------------------
class TestResult(models.Model):
    attempt = models.ForeignKey(QuizAttempt, on_delete=models.CASCADE, null=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE)
    score = models.IntegerField()
    is_pass = models.BooleanField(default=False, verbose_name="합격 여부")
    completed_at = models.DateTimeField(auto_now_add=True)
    attempt_number = models.IntegerField(default=0)

    def save(self, *args, **kwargs):
        if self.pk is None:
            previous_attempts = TestResult.objects.filter(user=self.user, quiz=self.quiz).count()
            self.attempt_number = previous_attempts + 1
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = '최종 결과'
        verbose_name_plural = '최종 결과'

    def __str__(self):
        return f"{self.user.username}의 '{self.quiz.title}' {self.attempt_number}차 ({self.completed_at.strftime('%Y-%m-%d %H:%M')}, {self.score}점)"


# ------------------------------------------------------------------
# 8. 사용자 답변 (UserAnswer)
# ------------------------------------------------------------------
class UserAnswer(models.Model):
    test_result = models.ForeignKey(TestResult, on_delete=models.CASCADE)
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    selected_choice = models.ForeignKey(Choice, on_delete=models.CASCADE, null=True, blank=True)
    short_answer_text = models.CharField(max_length=500, null=True, blank=True)
    is_correct = models.BooleanField()

    class Meta:
        verbose_name = '사용자 답변'
        verbose_name_plural = '사용자 답변'
        
    def __str__(self):
        answer = self.selected_choice.choice_text if self.selected_choice else self.short_answer_text
        return f"{self.question.question_text} -> {answer}"
    
class StudentLog(models.Model):
    """
    학생에 대한 기록 및 알림 (경고, 칭찬, 면담, 시스템 알림 등)
    """
    LOG_TYPES = [
        ('warning', '⚠️ 경고'),
        ('warning_letter', '📜 경고장'),
        ('counseling', '💬 면담/알림'),
        ('praise', '👏 칭찬'),
        ('system', '🔔 시스템'),
    ]

    profile = models.ForeignKey('accounts.Profile', on_delete=models.CASCADE, related_name='logs')
    log_type = models.CharField(max_length=20, choices=LOG_TYPES, default='system')
    reason = models.TextField(verbose_name="내용")
    
    # 누가 작성했는지 (시스템 자동인 경우 null 가능)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # 조치 완료 여부 (단순 알림은 생성 시 True로 설정)
    is_resolved = models.BooleanField(default=False)
    action_taken = models.TextField(blank=True, null=True, verbose_name="조치 사항")

    class Meta:
        ordering = ['-created_at']
        verbose_name = '학생 기록/알림'
        verbose_name_plural = '학생 기록/알림 목록'

    def __str__(self):
        return f"[{self.get_log_type_display()}] {self.profile.name} - {self.created_at.strftime('%m-%d')}"
    
class Notification(models.Model):
    """
    사용자(관리자/교육생)에게 보여줄 알림 데이터
    """
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications', verbose_name="받는 사람")
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sent_notifications', verbose_name="보낸 사람")
    
    message = models.CharField(max_length=255, verbose_name="알림 내용")
    notification_type = models.CharField(max_length=50, default='general', verbose_name="알림 유형") # counseling, warning 등
    related_url = models.CharField(max_length=255, blank=True, null=True, verbose_name="이동할 링크")
    
    is_read = models.BooleanField(default=False, verbose_name="읽음 여부")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="생성일시")

    class Meta:
        ordering = ['-created_at']
        verbose_name = '알림'
        verbose_name_plural = '알림 목록'

    def __str__(self):
        return f"{self.recipient}에게: {self.message}"
    
# [1] 시험 결과 테이블 (점수, 제출시간 등)
class QuizResult(models.Model):
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE)
    score = models.IntegerField(default=0)
    submitted_at = models.DateTimeField(auto_now_add=True)

    is_viewed = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.student} - {self.quiz} ({self.score}점)"

# [2] 학생이 제출한 답안 상세 (오답노트용)
class StudentAnswer(models.Model):
    result = models.ForeignKey(QuizResult, on_delete=models.CASCADE)
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    answer_text = models.TextField(blank=True, null=True) # 사용자가 적은 답
    is_correct = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.result} - {self.question.id}번 문제"