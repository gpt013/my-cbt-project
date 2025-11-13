from django.db import models
from django.contrib.auth.models import User
from django.contrib.auth.models import Group



# Quiz(시험지) 모델
class Quiz(models.Model):
    class Category(models.TextChoices):
        COMMON = '공통', '공통 (모든 교육생에게 표시)'
        PROCESS = '공정', '공정 (해당 공정 교육생에게 우선 표시)'

    title = models.CharField(max_length=200, verbose_name="퀴즈 제목")
    allowed_groups = models.ManyToManyField(Group, blank=True, verbose_name='응시 가능 그룹')
    
    # --- [핵심 추가] 카테고리 필드 ---
    category = models.CharField(
        max_length=10,
        choices=Category.choices,
        default=Category.COMMON,
        verbose_name="퀴즈 분류"
    )
    associated_process = models.CharField(
        max_length=100, 
        blank=True, null=True, 
        verbose_name="관련 공정",
        help_text="퀴즈 분류가 '공정'인 경우에만 이 필드를 채워주세요."
    )

    # --- 기존 출제 방식 필드 (누락 없음) ---
    class GenerationMethod(models.TextChoices):
        RANDOM = '랜덤', '난이도별 랜덤 출제'
        FIXED = '지정', '지정 문제 세트 출제'

    generation_method = models.CharField(
        max_length=10, 
        choices=GenerationMethod.choices, 
        default=GenerationMethod.RANDOM,
        verbose_name="문제 출제 방식"
    )
    exam_sheet = models.ForeignKey(
        'ExamSheet',
        on_delete=models.SET_NULL, 
        null=True, blank=True, 
        verbose_name="선택된 문제 세트",
        related_name='+' 
    )

    class Meta:
        verbose_name = '퀴즈'
        verbose_name_plural = '퀴즈'

    def __str__(self):
        return self.title
        

# Tag 모델 (Question 모델보다 먼저 정의)
class Tag(models.Model):
    name = models.CharField(max_length=50, unique=True, verbose_name='태그 이름')

    class Meta:
        verbose_name = '태그'
        verbose_name_plural = '태그'

    def __str__(self):
        return self.name

# Question(문제) 모델
class Question(models.Model):
    class QuestionType(models.TextChoices):
        SINGLE_CHOICE = '객관식'
        MULTIPLE_CHOICE = '다중선택'
        # --- [핵심 수정 1] ---
        SHORT_ANSWER = '주관식 (단일정답)' # 이름 변경
        SHORT_ANSWER_MULTIPLE = '주관식 (복수정답)' # 새 타입 추가

    class Difficulty(models.TextChoices):
        EASY = '하'
        MEDIUM = '중'
        HARD = '상'

    question_type = models.CharField(
        max_length=20, # <--- '주관식 (복수정답)'을 저장하기 위해 10에서 20으로 늘림
        choices=QuestionType.choices,
        default=QuestionType.SINGLE_CHOICE,
        verbose_name="문제 유형" # (admin에서 'Question type'으로 보임)
    )
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE)
    
    # --- [핵심 수정 2] ---
    # CharField를 TextField로 변경하여 칸 크기 및 엔터 문제 해결
    question_text = models.TextField(verbose_name="문제 내용") # (admin에서 'Question text'로 보임)
    # -------------------

    difficulty = models.CharField(
        max_length=2,
        choices=Difficulty.choices,
        default=Difficulty.EASY,
        verbose_name="난이도" # (admin에서 'Difficulty'로 보임)
    )
    image = models.ImageField(
        upload_to='quiz_images/', 
        blank=True, null=True, 
        verbose_name="이미지" # (admin에서 'Image'로 보임)
    )
    tags = models.ManyToManyField(Tag, blank=True, verbose_name='태그')

    class Meta:
        verbose_name = '문제'
        verbose_name_plural = '문제'

    def __str__(self):
        # 텍스트가 너무 길면 잘라서 표시
        if len(self.question_text) > 50:
            return self.question_text[:50] + "..."
        return self.question_text

class ExamSheet(models.Model):
    # --- [핵심 추가] 어떤 퀴즈에 대한 문제 세트인지 연결합니다 ---
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, verbose_name="관련 퀴즈")
    name = models.CharField(max_length=100, verbose_name="문제 세트 이름")
    questions = models.ManyToManyField('Question', verbose_name="포함된 문제들")

    class Meta:
        verbose_name = '문제 세트'
        verbose_name_plural = '퀴즈 관리 / 5. 문제 세트'

    def __str__(self):
        return f"{self.quiz.title} - {self.name}"

# Choice(보기) 모델
class Choice(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    choice_text = models.CharField(max_length=200, blank=True)
    is_correct = models.BooleanField(default=False)
    image = models.ImageField(upload_to='choice_images/', blank=True, null=True)

    class Meta:
        verbose_name = '보기'
        verbose_name_plural = '보기'

    def __str__(self):
        return self.choice_text

# 시험 응시 요청을 기록하는 모델
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
            previous_attempts = QuizAttempt.objects.filter(
                user=self.user, 
                quiz=self.quiz
            ).count()
            self.attempt_number = previous_attempts + 1
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = '응시 요청'
        verbose_name_plural = '응시 요청'

    def __str__(self):
        return f"{self.user.username}의 '{self.quiz.title}' {self.attempt_number}차 요청 ({self.status})"

# 전체 시험 결과 한 건을 저장하는 모델
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
            previous_attempts = TestResult.objects.filter(
                user=self.user, 
                quiz=self.quiz
            ).count()
            self.attempt_number = previous_attempts + 1
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = '최종 결과'
        verbose_name_plural = '최종 결과'

    def __str__(self):
        return f"{self.user.username}의 '{self.quiz.title}' {self.attempt_number}차 ({self.completed_at.strftime('%Y-%m-%d %H:%M')}, {self.score}점)"

# 각 문제에 대한 사용자의 답변을 저장하는 모델
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
        return f"{self.question.question_text} -> {self.selected_choice.choice_text if self.selected_choice else self.short_answer_text}"

