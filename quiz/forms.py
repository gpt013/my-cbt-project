from django import forms
from accounts.models import ManagerEvaluation, EvaluationItem, Cohort, Process, Company, Profile, StudentLog
from .models import Quiz, Question, Choice

# --- [기존] 평가 폼 ---
class EvaluationForm(forms.ModelForm):
    selected_items = forms.ModelMultipleChoiceField(
        queryset=EvaluationItem.objects.all(),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="세부 평가 항목"
    )

    class Meta:
        model = ManagerEvaluation
        fields = ['selected_items', 'overall_comment']
        widgets = {
            'overall_comment': forms.Textarea(attrs={
                'class': 'form-control', 
                'rows': 5,
                'placeholder': '교육생에 대한 종합적인 의견을 작성해주세요. (장단점, 특이사항 등)'
            }),
        }

# --- [신규] 매니저용 교육생 검색/필터 폼 ---
class TraineeFilterForm(forms.Form):
    cohort = forms.ModelChoiceField(
        queryset=Cohort.objects.all(), 
        required=False, 
        label="기수",
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'})
    )
    process = forms.ModelChoiceField(
        queryset=Process.objects.all(), 
        required=False, 
        label="공정",
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'})
    )
    status = forms.ChoiceField(
        choices=[('', '전체 상태')] + Profile.STATUS_CHOICES,
        required=False,
        label="상태",
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'})
    )
    search = forms.CharField(
        required=False, 
        label="검색",
        widget=forms.TextInput(attrs={'class': 'form-control form-select-sm', 'placeholder': '이름, 사번, ID 검색'})
    )

# --- [신규] 퀴즈 생성 마법사 (기초 폼) ---
class QuizWizardForm(forms.ModelForm):
    class Meta:
        model = Quiz
        fields = ['title', 'category', 'associated_process', 'generation_method', 'required_tags']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '예: 25-01기 반도체 공정 1차 평가'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'associated_process': forms.Select(attrs={'class': 'form-select'}),
            'generation_method': forms.Select(attrs={'class': 'form-select'}),
            'required_tags': forms.SelectMultiple(attrs={'class': 'form-control select2', 'style': 'height: 100px;'}), # Select2 라이브러리 사용 권장
        }

class QuizForm(forms.ModelForm):
    class Meta:
        model = Quiz
        fields = ['title', 'category', 'associated_process', 'generation_method', 'required_tags', 'allowed_groups', 'allowed_users']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '예: 25-01기 반도체 공정 1차 평가'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'associated_process': forms.Select(attrs={'class': 'form-select'}),
            'generation_method': forms.Select(attrs={'class': 'form-select'}),
            'required_tags': forms.SelectMultiple(attrs={'class': 'form-control', 'style': 'height: 100px;'}),
            'allowed_groups': forms.SelectMultiple(attrs={'class': 'form-control', 'style': 'height: 100px;'}),
            'allowed_users': forms.SelectMultiple(attrs={'class': 'form-control', 'style': 'height: 100px;'}),
        }

# [신규 추가] 문제 생성/수정 폼
class QuestionForm(forms.ModelForm):
    class Meta:
        model = Question
        fields = ['question_text', 'question_type', 'difficulty', 'tags', 'image']
        widgets = {
            'question_text': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'question_type': forms.Select(attrs={'class': 'form-select'}),
            'difficulty': forms.Select(attrs={'class': 'form-select'}),
            'tags': forms.SelectMultiple(attrs={'class': 'form-select'}),
            'image': forms.FileInput(attrs={'class': 'form-control'}),
        }

class StudentLogForm(forms.ModelForm):
    class Meta:
        model = StudentLog
        fields = ['log_type', 'reason', 'action_taken'] # action_taken 추가
        widgets = {
            'log_type': forms.Select(attrs={'class': 'form-select', 'id': 'id_log_type'}),
            'reason': forms.Textarea(attrs={
                'class': 'form-control', 
                'rows': 4, 
                'placeholder': '발생 내용 및 사유를 입력하세요. (육하원칙)'
            }),
            'action_taken': forms.Textarea(attrs={
                'class': 'form-control', 
                'rows': 2, 
                'placeholder': '조치 내용이나 합의 사항을 입력하세요. (선택)'
            }),
        }