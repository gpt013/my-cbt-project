from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import Profile, Company, PartLeader # PartLeader를 import합니다.

# UserCreationForm (기존과 동일, 누락 없음)
class CustomUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username',)

# ProfileForm (company 필드 추가 및 스타일링)
class ProfileForm(forms.ModelForm):
    # --- [핵심] __init__ 함수를 추가하여 'company', 'pl', 'process' 필드를 드롭다운으로 만듭니다 ---
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 'company' 필드
        self.fields['company'].required = True
        self.fields['company'].empty_label = "소속 회사를 선택하세요"
        self.fields['company'].widget.attrs.update({'class': 'form-select'})
        
        # 'process' 필드
        self.fields['process'].required = True
        self.fields['process'].empty_label = "공정을 선택하세요"
        self.fields['process'].widget.attrs.update({'class': 'form-select'})

        # 'pl' 필드
        self.fields['pl'].required = True
        self.fields['pl'].empty_label = "담당 PL님을 선택하세요"
        self.fields['pl'].widget.attrs.update({'class': 'form-select'})

    class Meta:
        model = Profile
        # --- [핵심 수정] 'pl_name'을 'pl'로 변경합니다 ---
        fields = ['company', 'name', 'employee_id', 'class_number', 'process', 'pl']

    # '공정' 필드 검증 (기존과 동일, 누락 없음)
    def clean_process(self):
        process_input = self.cleaned_data.get('process', '').upper()
        
        if process_input == 'DIFFUSION':
            process_input = 'DIFF'
        
        allowed_processes = ['CMP', 'IMP', 'CLEAN', 'DIFF', 'METAL', 'CVD', 'ETCH_LAM', 'ETCH_TAS']
        
        if process_input not in allowed_processes:
            raise forms.ValidationError("허용된 공정(CMP, IMP, CLEAN, DIFF, METAL, CVD, ETCH)이 아닙니다. 다시 확인해주세요.")
        
        return process_input