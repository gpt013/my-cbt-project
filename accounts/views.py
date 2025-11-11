# accounts/views.py (최종 수정본)

from django.shortcuts import render, redirect
from django.db import transaction
from .forms import CustomUserCreationForm, ProfileForm
from django.contrib import messages
from django.http import JsonResponse
from .models import PartLeader

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

def load_part_leaders(request):
    """
    AJAX 요청을 받아, 'company_id'와 'process_name'에 맞는 
    PartLeader 목록을 JSON으로 반환하는 뷰
    """
    company_id = request.GET.get('company_id')
    process_id = request.GET.get('process_id')

    # 두 값 중 하나라도 없으면 빈 목록 반환
    if not company_id or not process_id:
        return JsonResponse({'pls': []})

    try:
        # [수정 3] process__name=... 대신 process_id=... 로 필터링합니다.
        pls = PartLeader.objects.filter(
            company_id=company_id, 
            process_id=process_id  # <--- 여기가 핵심
        ).order_by('name')
        
        pl_list = [{"id": pl.id, "name": pl.name} for pl in pls]
        return JsonResponse({'pls': pl_list})
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)