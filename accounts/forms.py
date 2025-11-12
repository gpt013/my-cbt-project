# accounts/forms.py

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import Profile, Company, PartLeader, Process


# UserCreationForm (기존과 동일)
class CustomUserCreationForm(UserCreationForm):
    email = forms.EmailField(
        label="이메일",
        required=True, # ⬅️ 필수 항목으로 지정
        help_text="비밀번호 찾기 등에 사용되니 정확히 입력해 주세요."
    )

    class Meta(UserCreationForm.Meta):
        model = User
        # --- [핵심 2] 'email'을 fields에 추가 ---
        fields = ('username', 'email')
        # ---------------------------------------

    # --- [핵심 3] __init__을 추가하여 email 필드에도 스타일 적용 ---
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # 기존 'username' 필드 스타일링
        if 'username' in self.fields:
            self.fields['username'].widget.attrs.update({
                'class': 'form-control',
                'placeholder': '아이디'
            })
            
        # 새로 추가된 'email' 필드 스타일링
        if 'email' in self.fields:
            self.fields['email'].widget.attrs.update({
                'class': 'form-control',
                'placeholder': 'example@example.com'
            })


class ProfileForm(forms.ModelForm):

    class Meta:
        model = Profile
        fields = ['company', 'name', 'employee_id', 'class_number', 'process', 'pl']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # --- company 필드 ---
        self.fields['company'].required = True
        self.fields['company'].empty_label = "소속 회사를 선택하세요"
        self.fields['company'].widget.attrs.update({'class': 'form-select'})

        # --- process 필드 (ForeignKey → 기본 ModelChoiceField 그대로 사용) ---
        # queryset만 명시적으로 넣어 주고, 라벨/스타일만 손본다.
        self.fields['process'].queryset = Process.objects.all()
        self.fields['process'].empty_label = "공정을 선택하세요"
        self.fields['process'].widget.attrs.update({'class': 'form-select'})

        # --- pl 필드 ---
        self.fields['pl'].required = True
        self.fields['pl'].empty_label = "담당 PL님을 선택하세요"
        self.fields['pl'].widget.attrs.update({'class': 'form-select'})

    # ⚠️ clean_process는 더 이상 필요 없음 → 제거
    # Django 기본 ModelChoiceField가 알아서 Process 인스턴스로 변환해 준다.
