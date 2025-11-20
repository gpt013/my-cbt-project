# quiz/forms.py

from django import forms
# accounts 모델을 가져와야 합니다.
from accounts.models import ManagerEvaluation, EvaluationItem

class EvaluationForm(forms.ModelForm):
    # [핵심] 평가 항목을 체크박스 형태로 보여줍니다.
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
                'class': 'form-control', 
                'rows': 5,
                'placeholder': '교육생에 대한 종합적인 의견을 작성해주세요. (장단점, 특이사항 등)'
            }),
        }