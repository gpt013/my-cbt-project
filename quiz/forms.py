from django import forms
from accounts.models import ManagerEvaluation, EvaluationItem, Cohort, Process, Company, Profile
from .models import Quiz, Question, Choice, StudentLog, Tag

# [1] 평가 폼 (유지)
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

# [2] 필터 폼 (유지)
class TraineeFilterForm(forms.Form):
    cohort = forms.ModelChoiceField(queryset=Cohort.objects.all(), required=False, label="기수", widget=forms.Select(attrs={'class': 'form-select form-select-sm'}))
    process = forms.ModelChoiceField(queryset=Process.objects.all(), required=False, label="공정", widget=forms.Select(attrs={'class': 'form-select form-select-sm'}))
    status = forms.ChoiceField(choices=[('', '전체 상태')] + Profile.STATUS_CHOICES, required=False, label="상태", widget=forms.Select(attrs={'class': 'form-select form-select-sm'}))
    search = forms.CharField(required=False, label="검색", widget=forms.TextInput(attrs={'class': 'form-control form-select-sm', 'placeholder': '이름, 사번, ID 검색'}))

# [3] 퀴즈 마법사 & 폼 (유지)
class QuizWizardForm(forms.ModelForm):
    class Meta:
        model = Quiz
        fields = ['title', 'category', 'associated_process', 'generation_method', 'required_tags']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'associated_process': forms.Select(attrs={'class': 'form-select'}),
            'generation_method': forms.Select(attrs={'class': 'form-select'}),
            'required_tags': forms.SelectMultiple(attrs={'class': 'form-control', 'style': 'height: 100px;'}),
        }

class QuizForm(forms.ModelForm):
    class Meta:
        model = Quiz
        fields = ['title', 'category', 'associated_process', 'generation_method', 'required_tags', 'allowed_groups', 'allowed_users']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'associated_process': forms.Select(attrs={'class': 'form-select'}),
            'generation_method': forms.Select(attrs={'class': 'form-select'}),
            'required_tags': forms.SelectMultiple(attrs={'class': 'form-control', 'style': 'height: 100px;'}),
            'allowed_groups': forms.SelectMultiple(attrs={'class': 'form-control', 'style': 'height: 100px;'}),
            'allowed_users': forms.SelectMultiple(attrs={'class': 'form-control', 'style': 'height: 100px;'}),
        }

# -----------------------------------------------------------
# [4] 문제 생성 폼 (여기를 사진처럼 수정)
# -----------------------------------------------------------
class QuestionForm(forms.ModelForm):
    class Meta:
        model = Question
        fields = ['question_text', 'question_type', 'difficulty', 'tags', 'image']
        widgets = {
            'question_text': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'question_type': forms.Select(attrs={'class': 'form-select'}),
            'difficulty': forms.Select(attrs={'class': 'form-select'}),
            
            # [수정] 사진처럼 목록 상자(SelectMultiple)로 변경 + 높이 지정
            'tags': forms.SelectMultiple(attrs={
                'class': 'form-control', 
                'style': 'height: 150px;' # 사진처럼 길게 보이도록 설정
            }),
            
            'image': forms.FileInput(attrs={'class': 'form-control'}),
        }
    
    # 복잡한 save 로직 제거 (기본 동작 사용)

# [5] 로그 폼 (유지)
class StudentLogForm(forms.ModelForm):
    class Meta:
        model = StudentLog
        fields = ['log_type', 'reason', 'action_taken']
        widgets = {
            'log_type': forms.Select(attrs={'class': 'form-select'}),
            'reason': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'action_taken': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

class ChoiceForm(forms.ModelForm):
    class Meta:
        model = Choice
        fields = ['choice_text', 'is_correct']
        widgets = {
            # 여기서 Textarea 위젯을 사용하여 크기를 키웁니다.
            'choice_text': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,                 # 높이: 3줄 정도로 키움 (원하는 크기로 숫자 조절 가능)
                'style': 'resize: vertical;', # 사용자가 마우스로 크기 조절 가능하게 함
                'placeholder': '보기 내용을 입력하세요'
            }),
            'is_correct': forms.CheckboxInput(attrs={
                'class': 'form-check-input ms-2', # 체크박스 디자인
                'style': 'transform: scale(1.2);' # 체크박스도 약간 키움
            })
        }