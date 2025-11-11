from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import Profile, Company, PartLeader, Process

# UserCreationForm (기존과 동일, 누락 없음)
class CustomUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username',)

# ProfileForm (company 필드 추가 및 스타일링)
class ProfileForm(forms.ModelForm):
    # --- [핵심] __init__ 함수를 수정합니다 ---
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # 'company' 필드 (기존과 동일)
        self.fields['company'].required = True
        self.fields['company'].empty_label = "소속 회사를 선택하세요"
        self.fields['company'].widget.attrs.update({'class': 'form-select'})
        
        # --- [핵심 수정 2] 'process' 필드를 DB 데이터 기반 드롭다운으로 변경 ---
        # 1. 위젯을 Select(드롭다운)로 명시적으로 지정
        self.fields['process'].widget = forms.Select(attrs={'class': 'form-select'})
        # 2. Process 모델에서 모든 공정 데이터를 가져와 '선택' 옵션과 결합
        process_choices = [("", "공정을 선택하세요")] + [(p.name, p.name) for p in Process.objects.all()]
        # 3. choices(선택지)로 설정
        self.fields['process'].choices = process_choices
        self.fields['process'].required = True
        # -----------------------------------------------------------------

        # 'pl' 필드 (기존과 동일)
        self.fields['pl'].required = True
        self.fields['pl'].empty_label = "담당 PL님을 선택하세요"
        self.fields['pl'].widget.attrs.update({'class': 'form-select'})

    class Meta:
        model = Profile
        fields = ['company', 'name', 'employee_id', 'class_number', 'process', 'pl']

    # '공정' 필드 검증 (기존과 동일, 누락 없음)
   # def clean_process(self):
   #     process_input = self.cleaned_data.get('process', '').upper()
        
   #     if process_input == 'DIFFUSION':
   #         process_input = 'DIFF'
        
   #     allowed_processes = ['CMP', 'IMP', 'CLEAN', 'DIFF', 'METAL', 'CVD', 'ETCH_LAM', 'ETCH_TAS']
        
   #     if process_input not in allowed_processes:
   #         raise forms.ValidationError("허용된 공정(CMP, IMP, CLEAN, DIFF, METAL, CVD, ETCH)이 아닙니다. 다시 확인해주세요.")
        
   #     return process_input

def clean_process(self):
        # 폼에서 제출된 데이터(공정 이름, 예: "CMP")를 가져옵니다.
        process_name = self.cleaned_data.get('process')

        if not process_name:
             # 이 경우는 'required=True'에 의해 이미 걸러지지만, 안전을 위해 추가
            raise forms.ValidationError("공정을 선택해 주세요.")

        try:
            # 이름으로 실제 Process 객체를 찾습니다.
            process_object = Process.objects.get(name=process_name)
            # ModelForm이 저장할 수 있도록 '객체'를 반환합니다.
            return process_object
        except Process.DoesNotExist:
            # DB에 없는 값이 억지로 제출된 경우 (예: "C M P")
            raise forms.ValidationError("유효하지 않은 공정입니다. 다시 선택해 주세요.")
    # -----------------------