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


# 2. 프로필 입력 폼 (수정됨)
class ProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ['company', 'name', 'employee_id', 'cohort', 'process', 'pl']
        
        # ▼▼▼ [핵심 추가] 이 부분이 있어야 화면에 글자가 보입니다! ▼▼▼
        labels = {
            'company': '소속 회사',
            'name': '이름',
            'employee_id': '사번',
            'cohort': '기수',       # <-- 여기가 핵심입니다
            'process': '공정',
            'pl': '담당 PL',
        }
        
        # 디자인(CSS) 적용
        widgets = {
            'company': forms.Select(attrs={'class': 'form-select'}),
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '실명을 입력하세요'}),
            'employee_id': forms.TextInput(attrs={'class': 'form-control'}),
            'cohort': forms.Select(attrs={'class': 'form-select'}),
            'process': forms.Select(attrs={'class': 'form-select'}),
            'pl': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # 1. 필수 입력 설정 및 안내 문구
        self.fields['company'].empty_label = "소속 회사를 선택하세요"
        self.fields['process'].empty_label = "공정을 선택하세요"
        self.fields['pl'].empty_label = "담당 PL님을 선택하세요"
        
        # 2. 기수(Cohort) 필터링 설정
        # 가입 활성화(is_registration_open=True)된 기수만 목록에 표시
        self.fields['cohort'].queryset = Cohort.objects.filter(is_registration_open=True)
        self.fields['cohort'].empty_label = "소속 기수를 선택하세요"
        
        # ▼▼▼ [핵심 추가] 드롭다운에 날짜 없이 '기수 이름(예: 1기)'만 표시하는 설정 ▼▼▼
        self.fields['cohort'].label_from_instance = lambda obj: obj.name
        # ▲▲▲ ----------------------------------------------------------- ▲▲▲

        # 모든 필드 필수 입력으로 설정
        for field in self.fields:
            self.fields[field].required = True

    # --- [기존 유지] 기수 날짜 검증 로직 ---
    def clean_cohort(self):
        cohort = self.cleaned_data.get('cohort')
        today = timezone.now().date()

        if cohort:
            start = cohort.start_date
            end = cohort.end_date

            # 1. 아직 시작하지 않은 기수
            if start and today < start:
                raise forms.ValidationError(
                    f"선택하신 '{cohort.name}'는 아직 모집 기간이 아닙니다. (시작일: {start})"
                )
            
            # 2. 이미 끝난 기수
            if end and today > end:
                raise forms.ValidationError(
                    f"선택하신 '{cohort.name}'는 모집이 마감되었습니다. (종료일: {end})"
                )
        
        return cohort