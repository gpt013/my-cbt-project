from django.db import models
from django.contrib.auth.models import User
from django.contrib.auth.models import Group



# Quiz(시험지) 모델
class Quiz(models.Model):
    class GenerationMethod(models.TextChoices):
        RANDOM = '랜덤', '난이도별 랜덤 출제'
        FIXED = '지정', '지정 문제 세트 출제'
    title = models.CharField(max_length=200, verbose_name="퀴즈 제목")
    allowed_groups = models.ManyToManyField(Group, blank=True, verbose_name='응시 가능 그룹')

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
        SHORT_ANSWER = '주관식'

    class Difficulty(models.TextChoices):
        EASY = '하'
        MEDIUM = '중'
        HARD = '상'

    question_type = models.CharField(
        max_length=10,
        choices=QuestionType.choices,
        default=QuestionType.SINGLE_CHOICE,
    )
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE)
    question_text = models.CharField(max_length=200)
    difficulty = models.CharField(
        max_length=2,
        choices=Difficulty.choices,
        default=Difficulty.EASY,
    )
    image = models.ImageField(upload_to='quiz_images/', blank=True, null=True)
    tags = models.ManyToManyField(Tag, blank=True, verbose_name='태그')

    class Meta:
        verbose_name = '문제'
        verbose_name_plural = '문제'

    def __str__(self):
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

