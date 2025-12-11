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
        # 1. 수정 가능한 필드에 'joined_at'(입사일) 추가
        fields = ['name', 'employee_id', 'company', 'line', 'joined_at']
        
        labels = {
            'name': '이름',
            'employee_id': '사번',
            'company': '소속 회사',
            'line': '라인',
            'joined_at': '입사일 (교육 시작일)',
        }
        
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'employee_id': forms.TextInput(attrs={'class': 'form-control'}), # readonly 제거 (수정 가능)
            'company': forms.Select(attrs={'class': 'form-select'}),
            'line': forms.TextInput(attrs={'class': 'form-control'}),
            
            # [핵심] 연도 점프가 가능한 브라우저 기본 날짜 선택기 사용
            'joined_at': forms.DateInput(attrs={
                'class': 'form-control', 
                'type': 'date'  # 달력 아이콘 생성
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # 2. 소속 회사는 수정 불가능하게 설정 (보이기만 하고 비활성)
        if 'company' in self.fields:
            self.fields['company'].disabled = True
            self.fields['company'].help_text = "소속 회사는 수정할 수 없습니다. 관리자에게 문의하세요."
            
        # 3. 입사일 안내 문구
        if 'joined_at' in self.fields:
            self.fields['joined_at'].help_text = "입사일을 기준으로 연차가 자동 계산됩니다. (정확히 입력해주세요)"


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