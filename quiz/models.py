from django.db import models

# Quiz(시험지) 모델
class Quiz(models.Model):
    title = models.CharField(max_length=200) # 시험지 제목 (예: 코딩 능력 시험)

    def __str__(self):
        return self.title

# Question(문제) 모델 수정
class Question(models.Model):
    # --- 난이도 선택지를 정의합니다. ---
    class Difficulty(models.TextChoices):
        EASY = '하'
        MEDIUM = '중'
        HARD = '상'
    # --------------------------------

    # 어떤 시험지에 속한 문제인지 '연결'합니다.
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE)
    question_text = models.CharField(max_length=200)

    # --- 난이도 필드를 추가합니다. ---
    difficulty = models.CharField(
        max_length=2,
        choices=Difficulty.choices,
        default=Difficulty.EASY,
    )
    # -----------------------------

    def __str__(self):
        return self.question_text

# Choice(보기) 모델은 그대로 유지됩니다.
class Choice(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    choice_text = models.CharField(max_length=200)
    is_correct = models.BooleanField(default=False)

    def __str__(self):
        return self.choice_text