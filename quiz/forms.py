from django import forms
from accounts.models import ManagerEvaluation, EvaluationItem, Cohort, Process, Company, Profile
from .models import Quiz, Question, Choice, StudentLog, Tag

# [1] 평가 폼 (기존 유지)
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
                'class': 'form-control', 'rows': 5,
                'placeholder': '교육생에 대한 종합적인 의견을 작성해주세요.'
            }),
        }

# [2] 필터 폼 (기존 유지)
class TraineeFilterForm(forms.Form):
    cohort = forms.ModelChoiceField(
        queryset=Cohort.objects.all(), required=False, label="기수", 
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'})
    )
    process = forms.ModelChoiceField(
        queryset=Process.objects.all(), required=False, label="공정", 
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'})
    )
    status = forms.ChoiceField(
        choices=[('', '전체 상태')] + Profile.STATUS_CHOICES, required=False, label="상태", 
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'})
    )
    search = forms.CharField(
        required=False, label="검색", 
        widget=forms.TextInput(attrs={'class': 'form-control form-select-sm', 'placeholder': '이름, 사번, ID 검색'})
    )

# [3] 퀴즈 마법사 (간편 생성용)
class QuizWizardForm(forms.ModelForm):
    class Meta:
        model = Quiz
        # [수정] associated_process -> related_process 변경
        fields = ['title', 'category', 'related_process', 'generation_method', 'required_tags']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '시험 제목'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'related_process': forms.Select(attrs={'class': 'form-select'}),
            'generation_method': forms.Select(attrs={'class': 'form-select'}),
            'required_tags': forms.SelectMultiple(attrs={'class': 'form-control', 'style': 'height: 150px;'}),
        }

# [4] 퀴즈 전체 폼 (상세 설정용)
class QuizForm(forms.ModelForm):
    class Meta:
        model = Quiz
        # [수정] 모델의 모든 필드 반영 (설명, 문항수, 점수, 시간 등)
        fields = [
            'title', 'description', 'category', 'related_process', 
            'generation_method', 'question_count', 'pass_score', 'time_limit',
            'required_tags', 'questions', 'allowed_groups', 'allowed_users'
        ]
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': '시험 설명'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'related_process': forms.Select(attrs={'class': 'form-select'}),
            'generation_method': forms.Select(attrs={'class': 'form-select'}),
            
            # 숫자 입력 필드
            'question_count': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'pass_score': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'max': 100}),
            'time_limit': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),

            # M2M 필드 (높이 조절)
            'required_tags': forms.SelectMultiple(attrs={'class': 'form-control', 'style': 'height: 150px;'}),
            'questions': forms.SelectMultiple(attrs={'class': 'form-control', 'style': 'height: 200px;'}),
            'allowed_groups': forms.SelectMultiple(attrs={'class': 'form-control', 'style': 'height: 100px;'}),
            'allowed_users': forms.SelectMultiple(attrs={'class': 'form-control', 'style': 'height: 100px;'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        method = cleaned_data.get('generation_method')
        questions = cleaned_data.get('questions')
        required_tags = cleaned_data.get('required_tags')

        if method == 'fixed' and not questions:
            self.add_error('questions', "지정 출제 방식을 선택한 경우, 문제를 하나 이상 선택해야 합니다.")
        
        if method == 'random' and not required_tags:
            self.add_error('required_tags', "랜덤 출제 방식을 선택한 경우, 태그를 하나 이상 선택해야 합니다.")
            
        return cleaned_data

# [5] 문제 생성 폼 (요청하신 대로 태그 SelectMultiple 적용)
class QuestionForm(forms.ModelForm):
    class Meta:
        model = Question
        fields = ['question_text', 'question_type', 'difficulty', 'tags', 'image']
        widgets = {
            'question_text': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'question_type': forms.Select(attrs={'class': 'form-select'}),
            'difficulty': forms.Select(attrs={'class': 'form-select'}),
            
            # [핵심] 태그를 목록 상자로 표시하고 높이 지정
            'tags': forms.SelectMultiple(attrs={
                'class': 'form-control', 
                'style': 'height: 150px;' 
            }),
            
            'image': forms.FileInput(attrs={'class': 'form-control'}),
        }

# [6] 보기 생성 폼 (이미지 추가됨)
class ChoiceForm(forms.ModelForm):
    class Meta:
        model = Choice
        fields = ['choice_text', 'is_correct', 'image']
        widgets = {
            'choice_text': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'style': 'resize: vertical;',
                'placeholder': '보기 내용'
            }),
            'is_correct': forms.CheckboxInput(attrs={
                'class': 'form-check-input ms-2',
                'style': 'transform: scale(1.2);'
            }),
            'image': forms.FileInput(attrs={'class': 'form-control form-control-sm'}),
        }

# [7] 학생 로그 폼
class StudentLogForm(forms.ModelForm):
    class Meta:
        model = StudentLog
        fields = ['log_type', 'reason', 'is_resolved', 'action_taken']
        widgets = {
            'log_type': forms.Select(attrs={'class': 'form-select'}),
            'reason': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'is_resolved': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'action_taken': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }