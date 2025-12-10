# accounts/forms.py

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import Profile, Company, PartLeader, Process, Cohort
from django.utils import timezone

# 1. 회원가입 계정 생성 폼 (기존 동일)
class CustomUserCreationForm(UserCreationForm):
    email = forms.EmailField(
        label="이메일",
        required=True,
        help_text="비밀번호 찾기 등에 사용되니 정확히 입력해 주세요."
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'email')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'username' in self.fields:
            self.fields['username'].widget.attrs.update({
                'class': 'form-control',
                'placeholder': '아이디'
            })
        if 'email' in self.fields:
            self.fields['email'].widget.attrs.update({
                'class': 'form-control',
                'placeholder': 'example@example.com'
            })


# 2. 프로필 입력 폼 (가입 시 사용 - 전체 입력 가능)
class ProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ['company', 'name', 'employee_id', 'cohort', 'process', 'line', 'pl']
        
        labels = {
            'company': '소속 회사',
            'name': '이름',
            'employee_id': '사번',
            'cohort': '기수',
            'process': '공정',
            'line': '라인',
            'pl': '담당 PL',
        }
        
        widgets = {
            'company': forms.Select(attrs={'class': 'form-select'}),
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '실명을 입력하세요'}),
            'employee_id': forms.TextInput(attrs={'class': 'form-control'}),
            'cohort': forms.Select(attrs={'class': 'form-select'}),
            'process': forms.Select(attrs={'class': 'form-select', 'id': 'id_process'}), # ID 추가 (AJAX용)
            'line': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '상세 라인을 입력하세요'}),
            'pl': forms.Select(attrs={'class': 'form-select', 'id': 'id_pl'}), # ID 추가
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['company'].empty_label = "소속 회사를 선택하세요"
        self.fields['process'].empty_label = "공정을 선택하세요"
        self.fields['pl'].empty_label = "담당 PL님을 선택하세요"
        
        # 기수 필터링 (가입 중인 기수만)
        self.fields['cohort'].queryset = Cohort.objects.filter(is_registration_open=True)
        self.fields['cohort'].empty_label = "소속 기수를 선택하세요"
        self.fields['cohort'].label_from_instance = lambda obj: obj.name

        # 필수 입력 설정
        for name, field in self.fields.items():
            if name != 'line':
                field.required = True

    def clean_cohort(self):
        cohort = self.cleaned_data.get('cohort')
        today = timezone.now().date()
        if cohort:
            start = cohort.start_date
            end = cohort.end_date
            if start and today < start:
                raise forms.ValidationError(f"'{cohort.name}'는 아직 모집 기간이 아닙니다. (시작일: {start})")
            if end and today > end:
                raise forms.ValidationError(f"'{cohort.name}'는 모집이 마감되었습니다. (종료일: {end})")
        return cohort


# [신규 추가] 3. 프로필 수정 폼 (수정 시 사용 - 민감 정보 제한)
class ProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = Profile
        # 수정 가능한 필드만 포함 (기수, 공정, PL 제외)
        fields = ['name', 'employee_id', 'company', 'line']
        
        labels = {
            'name': '이름',
            'employee_id': '사번',
            'company': '소속 회사',
            'line': '라인',
        }
        
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'employee_id': forms.TextInput(attrs={'class': 'form-control', 'readonly': 'readonly'}), # 사번도 수정 불가 (읽기 전용)
            'company': forms.Select(attrs={'class': 'form-select'}),
            'line': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 사번 필드에 안내 메시지 추가
        if 'employee_id' in self.fields:
            self.fields['employee_id'].help_text = "사번은 수정할 수 없습니다. 관리자에게 문의하세요."


class EmailVerificationForm(forms.Form):
    code = forms.CharField(
        label="인증 코드 6자리",
        max_length=6,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-lg text-center', 
            'placeholder': '123456',
            'autofocus': 'autofocus'
        })
    )