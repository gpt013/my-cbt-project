# accounts/forms.py

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import Profile, Company, PartLeader, Process

# UserCreationForm (이메일 필드 포함된 수정본)
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


# ProfileForm
class ProfileForm(forms.ModelForm):

    class Meta:
        model = Profile
        # [수정] 'is_profile_complete' 필드는 여기서 관리하지 않으므로 제외
        fields = ['company', 'name', 'employee_id', 'class_number', 'process', 'pl']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # 'company' 필드 스타일링
        self.fields['company'].required = True
        self.fields['company'].empty_label = "소속 회사를 선택하세요"
        self.fields['company'].widget.attrs.update({'class': 'form-select'})

        # --- [핵심 수정] ---
        # 'process' 필드는 Django 기본 ModelChoiceField를 그대로 사용합니다.
        # (이것이 value를 ID로 만듭니다)
        # 1. 쿼리셋을 명확히 지정해줄 수 있습니다 (선택 사항).
        self.fields['process'].queryset = Process.objects.all()
        # 2. 스타일과 라벨만 수정합니다.
        self.fields['process'].required = True
        self.fields['process'].empty_label = "공정을 선택하세요"
        self.fields['process'].widget.attrs.update({'class': 'form-select'})
        
        # (choices를 강제로 덮어쓰는 코드를 삭제했습니다.)
        # ---------------------

        # 'pl' 필드 스타일링
        self.fields['pl'].required = True
        self.fields['pl'].empty_label = "담당 PL님을 선택하세요"
        self.fields['pl'].widget.attrs.update({'class': 'form-select'})

    # (clean_process 메서드가 필요 없습니다. ModelChoiceField가 ID를 객체로 자동 변환합니다.)