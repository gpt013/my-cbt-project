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
# 2. 문제(Question) 모델
# ------------------------------------------------------------------
class Question(models.Model):
    class QuestionType(models.TextChoices):
        SINGLE_CHOICE = 'multiple_choice', '객관식 (단일 정답)'     # 값 수정: admin과 통일성을 위해 영어 code 사용 권장
        MULTIPLE_SELECT = 'multiple_select', '객관식 (복수 정답)'
        SHORT_ANSWER = 'short_answer', '주관식 (단답형)'
        TRUE_FALSE = 'true_false', 'OX 퀴즈'

    class Difficulty(models.TextChoices):
        LOW = 'low', '하'
        MEDIUM = 'medium', '중'
        HIGH = 'high', '상'

    question_text = models.TextField(verbose_name="문제 내용")
    question_type = models.CharField(
        max_length=50,
        choices=QuestionType.choices,
        default=QuestionType.SINGLE_CHOICE,
        verbose_name="문제 유형"
    )
    difficulty = models.CharField(
        max_length=10,
        choices=Difficulty.choices,
        default=Difficulty.MEDIUM,
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
        return self.question_text[:50]


# ------------------------------------------------------------------
# 3. 보기(Choice) 모델
# ------------------------------------------------------------------
class Choice(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='choice_set') # admin의 ChoiceInline 사용 위해 related_name 주의
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
    quiz = models.ForeignKey('Quiz', on_delete=models.CASCADE, verbose_name="관련 퀴즈")
    name = models.CharField(max_length=100, verbose_name="문제 세트 이름")
    questions = models.ManyToManyField(Question, verbose_name="포함된 문제들")

    class Meta:
        verbose_name = '문제 세트'
        verbose_name_plural = '퀴즈 관리 / 5. 문제 세트'

    def __str__(self):
        return f"{self.quiz.title} - {self.name}"


# ------------------------------------------------------------------
# 5. 퀴즈(Quiz) 모델 - [핵심 수정: 필드 추가 및 보완]
# ------------------------------------------------------------------
class Quiz(models.Model):
    class Category(models.TextChoices):
        COMMON = '공통', '공통 (모든 교육생에게 표시)'
        PROCESS = '공정', '공정 (해당 공정 교육생에게 우선 표시)'

    class GenerationMethod(models.TextChoices):
        RANDOM = 'random', '랜덤 출제 (태그 기반)'
        FIXED = 'fixed', '지정 출제 (문제 직접 선택)'

    title = models.CharField(max_length=200, verbose_name="퀴즈 제목")
    description = models.TextField(verbose_name="시험 설명", blank=True) # [추가]
    
    # 1. 권한 설정
    allowed_groups = models.ManyToManyField(Group, blank=True, verbose_name='응시 가능 그룹')
    allowed_users = models.ManyToManyField(
        User, blank=True, verbose_name="개별 응시 허용 인원", related_name='allowed_quizzes'
    )

    # 2. 분류 및 방식
    category = models.CharField(
        max_length=10, choices=Category.choices, default=Category.COMMON, verbose_name="퀴즈 분류"
    )
    # [수정] associated_process -> related_process (Admin과 통일)
    related_process = models.ForeignKey(
        Process, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="관련 공정"
    )
    generation_method = models.CharField(
        max_length=10, choices=GenerationMethod.choices, default=GenerationMethod.RANDOM, verbose_name="문제 출제 방식"
    )

    # 3. 시험 규칙 설정 [추가된 필드들]
    question_count = models.IntegerField(default=25, verbose_name="출제 문항 수")
    pass_score = models.IntegerField(default=80, verbose_name="합격 기준 점수")
    time_limit = models.IntegerField(default=30, verbose_name="제한 시간(분)")

    # 4. 문제 구성
    questions = models.ManyToManyField(
        Question, blank=True, related_name='quizzes', verbose_name="포함된 문제들 (지정 방식용)"
    )
    required_tags = models.ManyToManyField(
        Tag, blank=True, verbose_name="출제 포함 태그 (랜덤 방식용)"
    )
    
    # 작성자 정보 [추가]
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="작성자"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    # (구버전 호환용) ExamSheet 연결
    exam_sheet = models.ForeignKey(
        ExamSheet, on_delete=models.SET_NULL, null=True, blank=True, 
        verbose_name="선택된 문제 세트 (구버전)", related_name='+' 
    )

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
    
    attempt_number = models.IntegerField(default=0)
    requested_at = models.DateTimeField(auto_now_add=True) # 요청 시간
    started_at = models.DateTimeField(null=True, blank=True) # 실제 시작 시간
    completed_at = models.DateTimeField(null=True, blank=True) # 완료 시간 (중복 방지용 필드)

    def save(self, *args, **kwargs):
        if self.pk is None:
            previous_attempts = QuizAttempt.objects.filter(user=self.user, quiz=self.quiz).count()
            self.attempt_number = previous_attempts + 1
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = '응시 요청/기록'
        verbose_name_plural = '응시 요청/기록'

    def __str__(self):
        return f"{self.user.username} - {self.quiz.title} ({self.status})"


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
        return f"{self.user.username} - {self.quiz.title} : {self.score}점"


# ------------------------------------------------------------------
# 8. 사용자 답변 (UserAnswer)
# ------------------------------------------------------------------
class UserAnswer(models.Model):
    test_result = models.ForeignKey(TestResult, on_delete=models.CASCADE)
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    
    # 객관식 선택
    selected_choice = models.ForeignKey(Choice, on_delete=models.CASCADE, null=True, blank=True)
    # 주관식 입력
    short_answer_text = models.CharField(max_length=500, null=True, blank=True)
    
    is_correct = models.BooleanField()

    class Meta:
        verbose_name = '사용자 답변 상세'
        verbose_name_plural = '사용자 답변 상세'
        
    def __str__(self):
        return f"{self.test_result} - {self.question.id}"


# ------------------------------------------------------------------
# 9. 학생 기록 (StudentLog)
# ------------------------------------------------------------------
class StudentLog(models.Model):
    LOG_TYPES = [
        ('warning', '⚠️ 경고'),
        ('warning_letter', '🚫 경고장'),
        ('counseling', '💬 면담'),
        ('compliment', '👏 칭찬'),
        ('etc', '📝 기타'),
        ('exam_fail', '❌ 시험 불합격'),
    ]
    # accounts 앱의 Profile 모델과 연결
    profile = models.ForeignKey('accounts.Profile', on_delete=models.CASCADE, related_name='student_logs')
    recorder = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    
    log_type = models.CharField(max_length=20, choices=LOG_TYPES, default='counseling')
    reason = models.TextField()
    action_taken = models.TextField(blank=True, null=True)
    
    # 시험과 연결 (기존에 있었던 필드)
    related_quiz = models.ForeignKey('Quiz', on_delete=models.SET_NULL, null=True, blank=True)
    stage = models.IntegerField(default=1) # 몇 차 경고인지
    
    is_resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"[{self.get_log_type_display()}] {self.profile.name}"


# ------------------------------------------------------------------
# 10. 알림 (Notification)
# ------------------------------------------------------------------
class Notification(models.Model):
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications', verbose_name="받는 사람")
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sent_notifications', verbose_name="보낸 사람")
    
    message = models.CharField(max_length=255, verbose_name="알림 내용")
    notification_type = models.CharField(max_length=50, default='general', verbose_name="알림 유형") 
    related_url = models.CharField(max_length=255, blank=True, null=True, verbose_name="이동할 링크")
    
    is_read = models.BooleanField(default=False, verbose_name="읽음 여부")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="생성일시")

    class Meta:
        ordering = ['-created_at']
        verbose_name = '알림'
        verbose_name_plural = '알림 목록'

    def __str__(self):
        return f"{self.recipient}에게: {self.message}"


# ------------------------------------------------------------------
# 11. (레거시/보조) QuizResult & StudentAnswer
# ------------------------------------------------------------------
# *주의*: 위쪽의 TestResult/UserAnswer와 역할이 중복되지만, 
# 기존 코드 누락 방지를 위해 남겨둡니다. (필요 없으면 나중에 삭제)

class QuizResult(models.Model):
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE)
    score = models.IntegerField(default=0)
    submitted_at = models.DateTimeField(auto_now_add=True)
    is_viewed = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.student} - {self.quiz} ({self.score}점)"

class StudentAnswer(models.Model):
    result = models.ForeignKey(QuizResult, on_delete=models.CASCADE)
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    answer_text = models.TextField(blank=True, null=True) 
    is_correct = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.result} - {self.question.id}번 문제"