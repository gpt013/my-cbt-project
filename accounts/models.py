from django.db import models
from django.contrib.auth.models import User
import re

class Badge(models.Model):
    name = models.CharField(max_length=100, verbose_name="뱃지 이름")
    description = models.TextField(verbose_name="획득 조건 설명")
    image = models.ImageField(upload_to='badges/', blank=True, null=True, verbose_name="뱃지 이미지")

    class Meta:
        verbose_name = "뱃지"
        verbose_name_plural = "뱃지"

    def __str__(self):
        return self.name

class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=50, verbose_name='이름')
    employee_id = models.CharField(max_length=50, verbose_name='사번')
    class_number = models.CharField(max_length=50, verbose_name='기수')
    process = models.CharField(max_length=100, verbose_name='공정')
    pl_name = models.CharField(max_length=50, verbose_name='PL님 성함')
    badges = models.ManyToManyField(Badge, blank=True, verbose_name="획득한 뱃지")

    def save(self, *args, **kwargs):
        # '기수' 필드에서 숫자만 남깁니다. (예: "30기" -> "30")
        self.class_number = re.sub(r'[^0-9]', '', self.class_number)

        # '공정' 필드를 대문자로 변환합니다.
        if self.process:
            self.process = self.process.upper()
            if self.process == 'DIFFUSION':
                self.process = 'DIFF'
        
        super().save(*args, **kwargs) # 원래의 저장 기능을 호출

    def __str__(self):
        return f"{self.user.username}의 프로필"