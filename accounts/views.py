# accounts/views.py (최종 수정본)

from django.shortcuts import render, redirect
from django.db import transaction
from .forms import CustomUserCreationForm, ProfileForm
from django.contrib import messages

def signup(request):
    if request.user.is_authenticated:
        return redirect('/quiz/')

    if request.method == 'POST':
        user_form = CustomUserCreationForm(request.POST)
        profile_form = ProfileForm(request.POST)

        if user_form.is_valid() and profile_form.is_valid():
            try:
                with transaction.atomic():
                    user = user_form.save(commit=False)
                    user.is_active = False # 관리자 승인 대기
                    user.save()

                    profile = profile_form.save(commit=False)
                    profile.user = user
                    profile.save()
            
            except Exception as e:
                messages.error(request, f"가입 중 오류가 발생했습니다: {e}")
                return render(request, 'accounts/signup.html', {
                    'user_form': user_form,
                    'profile_form': profile_form
                })

            messages.success(request, "가입 신청이 완료되었습니다. 관리자의 승인을 기다려 주세요.")
            return redirect('accounts:login')
    else:
        user_form = CustomUserCreationForm()
        profile_form = ProfileForm()

    return render(request, 'accounts/signup.html', {
        'user_form': user_form,
        'profile_form': profile_form
    })