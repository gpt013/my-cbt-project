from django.db import models
from django.contrib.auth.models import User, Group
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db.models import Avg

# ------------------------------------------------------------------
# [0] 공정(Process) 모델
# (Quiz 모델에서 related_process 필드로 참조하므로 가장 위에 정의)
# ------------------------------------------------------------------
# accounts.models에 이미 Process가 있다면 import해서 쓰지만,
# 여기서는 요청하신 코드 구조 상 quiz/models.py 내에서 정의된 것으로 간주하고
# 최상단에 배치하여 순서 오류를 해결합니다.
# 만약 accounts 앱의 Process를 써야 한다면 아래 클래스는 주석 처리하고
# from accounts.models import Process 구문을 사용해야 합니다.
# (사용자님이 주신 코드에 accounts.models import가 있어도, 여기서 재정의가 필요하다면 사용)

# [주의] 아래 클래스 정의는 기존 코드에 없었으나 'related_process' 필드 오류 해결을 위해 
# accounts.models.Process를 참조하거나, 자체 정의가 필요합니다.
# 이미 accounts.models에서 import Process 했다면 이 클래스는 삭제하고,
# Quiz 모델에서 ForeignKey('accounts.Process', ...) 로 쓰셔도 됩니다.
# 하지만 순서 문제 해결을 위해 명시적으로 필요한 경우를 대비해 아래와 같이 배치합니다.
# (기존 코드에 Process 클래스 정의가 없었다면 import한 것을 사용하므로 이 부분은 건너뜁니다.)
# from accounts.models import Process  <-- 맨 위에서 이미 import 됨.

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
        SINGLE_CHOICE = 'multiple_choice', '객관식 (단일 정답)'
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
# 4. 시험지 세트 (ExamSheet)
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
# 5. 퀴즈(Quiz) 모델 - [핵심 수정 적용됨]
# ------------------------------------------------------------------
class Quiz(models.Model):
    # ▼▼▼ [핵심 수정] 4가지 분류 정의 ▼▼▼
    class Category(models.TextChoices):
        COMMON = 'common', '공통 (모든 교육생에게 표시)'
        PROCESS = 'process', '공정 (해당 공정 교육생에게 우선 표시)'
        SAFETY = 'safety', '안전'    # [추가됨]
        ETC = 'etc', '기타'          # [추가됨]

    class GenerationMethod(models.TextChoices):
        RANDOM = 'random', '랜덤 출제 (태그 기반)'
        FIXED = 'fixed', '지정 출제 (문제 직접 선택)'

    title = models.CharField(max_length=200, verbose_name="퀴즈 제목")
    description = models.TextField(verbose_name="시험 설명", blank=True)
    
    # 1. 권한 설정
    allowed_groups = models.ManyToManyField(Group, blank=True, verbose_name='응시 가능 그룹')
    allowed_users = models.ManyToManyField(
        User, blank=True, verbose_name="개별 응시 허용 인원", related_name='allowed_quizzes'
    )

    # 2. 분류 및 방식
    category = models.CharField(
        max_length=10, 
        choices=Category.choices, 
        default=Category.COMMON, 
        verbose_name="퀴즈 분류"
    )
    
    # [주의] 순환 참조 방지를 위해 문자열 'accounts.Process' 사용 권장
    # from accounts.models import Process 가 되어있다면 모델명 그대로 사용 가능
    related_process = models.ForeignKey(
        'accounts.Process',  # 문자열 참조로 순서 문제 해결
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        verbose_name="관련 공정"
    )
    
    generation_method = models.CharField(
        max_length=10, 
        choices=GenerationMethod.choices, 
        default=GenerationMethod.RANDOM, 
        verbose_name="문제 출제 방식"
    )

    # 3. 시험 규칙 설정
    question_count = models.IntegerField(default=25, verbose_name="출제 문항 수")
    pass_score = models.IntegerField(default=80, verbose_name="합격 기준 점수")
    time_limit = models.IntegerField(default=30, verbose_name="제한 시간(분)")

    # 4. 문제 구성
    questions = models.ManyToManyField(
        'Question', blank=True, related_name='quizzes', verbose_name="포함된 문제들 (지정 방식용)"
    )
    required_tags = models.ManyToManyField(
        'Tag', blank=True, verbose_name="출제 포함 태그 (랜덤 방식용)"
    )
    
    # 작성자 정보
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="작성자"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    # (구버전 호환용) ExamSheet 연결
    exam_sheet = models.ForeignKey(
        'ExamSheet', on_delete=models.SET_NULL, null=True, blank=True, 
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
    completed_at = models.DateTimeField(null=True, blank=True) # 완료 시간

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
    
    # 시험과 연결
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
    
@receiver(post_save, sender=TestResult)
def update_final_assessment_stats(sender, instance, created, **kwargs):
    """
    시험 결과가 나오면 -> FinalAssessment의 '시험 평균 점수'를 즉시 재계산
    """
    try:
        user = instance.user
        if not hasattr(user, 'profile'):
            return

        # 1. 해당 유저의 모든 시험 점수 평균 계산
        avg_data = TestResult.objects.filter(user=user).aggregate(avg=Avg('score'))
        new_avg = avg_data['avg'] if avg_data['avg'] is not None else 0

        # 2. FinalAssessment 가져오기 (없으면 생성)
        # accounts 앱의 모델을 가져와야 하므로 안에서 import (순환 참조 방지)
        from accounts.models import FinalAssessment
        
        assessment, _ = FinalAssessment.objects.get_or_create(profile=user.profile)

        # 3. 점수 업데이트 (값이 다를 때만 저장)
        if assessment.exam_avg_score != new_avg:
            assessment.exam_avg_score = round(new_avg, 1)
            assessment.save() # 저장 시 accounts/models.py의 Signal이 발동하여 환산점수/등수까지 자동 계산됨
            
    except Exception as e:
        print(f"❌ [통계 갱신 오류] {e}")