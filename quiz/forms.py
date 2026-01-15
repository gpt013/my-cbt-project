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
        # 사용자님 코드의 모든 필드 유지
        fields = [
            'title', 'description', 'category', 'related_process', 
            'generation_method', 'question_count', 'pass_score', 'time_limit',
            'required_tags', 'questions', 'allowed_groups', 'allowed_users'
        ]
        
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '시험 제목을 입력하세요'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': '시험에 대한 설명을 입력하세요'}),
            
            # [중요] category는 모델의 choices를 자동으로 가져와 드롭다운을 만듭니다.
            'category': forms.Select(attrs={'class': 'form-select', 'id': 'id_category'}),
            'related_process': forms.Select(attrs={'class': 'form-select', 'id': 'id_related_process'}),
            
            'generation_method': forms.Select(attrs={'class': 'form-select'}),
            
            # 숫자 입력 필드
            'question_count': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'pass_score': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'max': 100}),
            'time_limit': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),

            # M2M 필드 (높이 조절 및 다중 선택)
            'required_tags': forms.SelectMultiple(attrs={'class': 'form-control', 'style': 'height: 150px;'}),
            'questions': forms.SelectMultiple(attrs={'class': 'form-control', 'style': 'height: 200px;'}),
            'allowed_groups': forms.SelectMultiple(attrs={'class': 'form-control', 'style': 'height: 100px;'}),
            'allowed_users': forms.SelectMultiple(attrs={'class': 'form-control', 'style': 'height: 100px;'}),
        }
        
        labels = {
            'title': '시험 제목',
            'category': '퀴즈 분류',
            'related_process': '관련 공정',
            'generation_method': '출제 방식',
            'question_count': '문항 수',
            'pass_score': '합격 점수',
            'time_limit': '제한 시간(분)',
            'required_tags': '필수 포함 태그',
            'questions': '지정 문제 선택',
            'allowed_groups': '응시 허용 그룹',
            'allowed_users': '응시 허용 사용자',
        }

    def clean(self):
        cleaned_data = super().clean()
        
        # 데이터 가져오기
        category = cleaned_data.get('category')
        related_process = cleaned_data.get('related_process')
        generation_method = cleaned_data.get('generation_method')
        questions = cleaned_data.get('questions')
        required_tags = cleaned_data.get('required_tags')

        # [핵심 수정 2] 분류가 '공정'인데 관련 공정을 선택하지 않은 경우 에러
        if category in ['공정', 'process'] and not related_process:
            self.add_error('related_process', "분류가 '공정'인 경우, 반드시 관련 공정을 선택해야 합니다.")

        # [기존 로직 유지] 출제 방식에 따른 유효성 검사
        # models.py의 Choices 값에 따라 '지정'/'fixed' 등 값 확인 필요 (여기서는 한글 기준 작성)
        if generation_method in ['지정', 'fixed'] and not questions:
            self.add_error('questions', "지정 출제 방식을 선택한 경우, 문제를 하나 이상 선택해야 합니다.")
        
        if generation_method in ['태그', 'tag'] and not required_tags:
            self.add_error('required_tags', "태그 출제 방식을 선택한 경우, 태그를 하나 이상 선택해야 합니다.")
            
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