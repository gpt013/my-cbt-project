# accounts/views.py (수정 완료)

from django.shortcuts import render, redirect
from django.db import transaction
from .forms import CustomUserCreationForm, ProfileForm
from django.contrib import messages
from django.http import JsonResponse
# --- [핵심 1] import 수정 ---
from .models import PartLeader, Profile
from django.contrib.auth.decorators import login_required
# -------------------------

# --- [핵심 2] signup 뷰 수정 (ProfileForm 제거) ---
def signup(request):
    if request.user.is_authenticated:
        # (로그인한 사용자는 마이페이지로 보냅니다)
        return redirect('quiz:my_page') 

    if request.method == 'POST':
        user_form = CustomUserCreationForm(request.POST)
        # (ProfileForm 로직 삭제)

        if user_form.is_valid():
            try:
                with transaction.atomic():
                    user = user_form.save(commit=False)
                    user.is_active = False # 관리자 승인 대기
                    user.save()
                    
                    # (profile.save() 로직 삭제 -> 1단계의 Signal이 자동 처리)
            
            except Exception as e:
                messages.error(request, f"가입 중 오류가 발생했습니다: {e}")
                return render(request, 'accounts/signup.html', {
                    'user_form': user_form,
                    # (profile_form 컨텍스트 삭제)
                })

            messages.success(request, "가입 신청이 완료되었습니다. 관리자의 승인을 기다려 주세요.")
            return redirect('accounts:login')
    else:
        user_form = CustomUserCreationForm()
        # (ProfileForm 생성 로직 삭제)

    return render(request, 'accounts/signup.html', {
        'user_form': user_form,
        # (profile_form 컨텍스트 삭제)
    })
# --- [ / signup 뷰 수정 끝] ---


# --- [핵심 3] complete_profile 뷰 새로 추가 ---
@login_required
def complete_profile(request):
    """
    로그인은 했으나, 아직 개인정보를 입력하지 않은 사용자가
    정보를 입력하도록 강제하는 뷰.
    """
    # 1. profile 가져오기 (1단계의 Signal이 생성을 보장)
    profile = request.user.profile
    
    # 2. 이미 프로필을 완성했다면 메인 페이지로 보냄
    if profile.is_profile_complete:
        return redirect('quiz:my_page')

    if request.method == 'POST':
        # 3. ProfileForm을 여기서 사용 (instance=profile 필수)
        form = ProfileForm(request.POST, instance=profile)
        if form.is_valid():
            profile = form.save()
            # 4. '완료' 플래그를 True로 설정
            profile.is_profile_complete = True
            profile.save()
            
            messages.success(request, "프로필이 완성되었습니다. CBT 사이트 이용을 시작하세요!")
            return redirect('quiz:my_page')
    else:
        form = ProfileForm(instance=profile) # 폼을 'profile'의 기존 정보로 채움

    return render(request, 'accounts/complete_profile.html', {
        'profile_form': form,
        'is_completing_profile': True # (base.html 네비게이션 숨김용)
    })
# --- [ / complete_profile 뷰 추가 끝] ---


def load_part_leaders(request):
    """
    AJAX 요청을 받아, 'company_id'와 'process_id'에 맞는 
    PartLeader 목록을 JSON으로 반환하는 뷰
    """
    company_id = request.GET.get('company_id')
    
    # --- [핵심 확인 1] ---
    # 'process_name'이 아니라 'process_id'를 받아야 합니다.
    process_id = request.GET.get('process_id') 
    # ---------------------

    if not company_id or not process_id:
        return JsonResponse({'pls': []})

    try:
        # --- [핵심 확인 2] ---
        # 'process__name=...'이 아니라 'process_id=...'로 필터링해야 합니다.
        pls = PartLeader.objects.filter(
            company_id=company_id, 
            process_id=process_id  
        ).order_by('name')
        # ---------------------
        
        pl_list = [{"id": pl.id, "name": pl.name} for pl in pls]
        return JsonResponse({'pls': pl_list})
        
    except Exception as e:
        # (숫자가 아닌 'asd' 같은 값이 들어오면 여기서 500 오류가 납니다)
        return JsonResponse({'error': str(e)}, status=500)