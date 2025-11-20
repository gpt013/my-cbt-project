# accounts/forms.py

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import Profile, Company, PartLeader, Process, Cohort
from django.utils import timezone # 날짜 비교용

# UserCreationForm (기존과 동일)
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


# ProfileForm (검증 로직 추가됨)
class ProfileForm(forms.ModelForm):

    class Meta:
        model = Profile
        fields = ['company', 'name', 'employee_id', 'cohort', 'process', 'pl']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # 1. company 필드
        self.fields['company'].required = True
        self.fields['company'].empty_label = "소속 회사를 선택하세요"
        self.fields['company'].widget.attrs.update({'class': 'form-select'})

        # 2. cohort (기수) 필드 설정
        # [수정] 날짜 필터링을 제거했습니다.
        # Admin에서 '가입 활성화' 체크한 기수는 날짜 상관없이 목록에 다 보입니다.
        self.fields['cohort'].queryset = Cohort.objects.filter(is_registration_open=True)
        self.fields['cohort'].empty_label = "소속 기수를 선택하세요"
        self.fields['cohort'].widget.attrs.update({'class': 'form-select'})
        self.fields['cohort'].required = True

        # 3. process 필드
        self.fields['process'].queryset = Process.objects.all()
        self.fields['process'].empty_label = "공정을 선택하세요"
        self.fields['process'].widget.attrs.update({'class': 'form-select'})
        self.fields['process'].required = True

        # 4. pl 필드
        self.fields['pl'].required = True
        self.fields['pl'].empty_label = "담당 PL님을 선택하세요"
        self.fields['pl'].widget.attrs.update({'class': 'form-select'})

    # --- [핵심 추가] 기수 날짜 검증 로직 ---
    def clean_cohort(self):
        cohort = self.cleaned_data.get('cohort')
        today = timezone.now().date()

        if cohort:
            # 기수의 시작일/종료일이 설정되어 있는지 확인
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
    # -------------------------------------