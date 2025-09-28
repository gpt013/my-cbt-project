from django.contrib import admin
from .models import Question, Choice, Quiz # Quiz 추가

admin.site.register(Quiz) # Quiz 등록
admin.site.register(Question)
admin.site.register(Choice)