# accounts/forms.py (최종 수정본)

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import Profile

# UserCreationForm을 상속받아 기본 보안 기능을 모두 사용합니다.
class CustomUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username',) # ID 필드만 사용

# Profile 모델을 위한 폼
class ProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ['name', 'employee_id', 'class_number', 'process', 'pl_name']

    # --- '공정' 필드에 대한 특별 검증 함수 (들여쓰기 수정) ---
    def clean_process(self):
        process_input = self.cleaned_data.get('process', '').upper()
        
        # 'DIFFUSION'을 'DIFF'로 자동 변경
        if process_input == 'DIFFUSION':
            process_input = 'DIFF'
        
        allowed_processes = ['CMP', 'IMP', 'CLEAN', 'DIFF', 'METAL', 'CVD', 'ETCH_LAM', 'ETCH_TAS']
        
        if process_input not in allowed_processes:
            # 허용된 공정이 아니면, 오류를 발생시켜 사용자에게 알림
            raise forms.ValidationError("허용된 공정(CMP, IMP, CLEAN, DIFF, METAL, CVD, ETCH)이 아닙니다. 다시 확인해주세요.")
        
        return process_input # 검증을 통과한 값을 반환