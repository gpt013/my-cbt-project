from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import logout, login, authenticate
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.conf import settings
from django.utils import timezone
from django.http import JsonResponse
from django.db.models import Sum, Count, Q
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth import login as auth_login

# forms.py에서 정의한 폼들 import
from .forms import CustomUserCreationForm, ProfileForm, ProfileUpdateForm
# models.py에서 정의한 모델들 import
from .models import PartLeader, Profile

from quiz.models import TestResult        # 결과는 quiz 앱에서
from django.urls import reverse
from quiz.models import Notification


# ---------------------------------------------------
# 1. 회원가입 (이메일 인증 제거 -> 관리자 승인 대기)
# ---------------------------------------------------
def signup(request):
    if request.user.is_authenticated:
        return redirect('quiz:my_page')

    if request.method == 'POST':
        # [핵심] 이메일 중복 확인
        email = request.POST.get('email')
        if User.objects.filter(email=email).exists():
            messages.error(request, "이미 가입된 이메일입니다. 로그인해주세요.")
            return redirect('accounts:signup')

        # 신규 가입 처리
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.is_active = True 
            user.save() # ★ 여기서 시그널에 의해 프로필이 자동 생성될 수 있음

            # ★ [수정됨] IntegrityError 방지: create 대신 get_or_create 사용
            # "프로필이 이미 있으면 가져오고(get), 없으면 만들어라(create)"
            profile, created = Profile.objects.get_or_create(user=user)
            
            # 값 업데이트 (승인 대기 상태로 설정)
            profile.is_approved = False       # ★ 핵심: 관리자 승인 전까지 이용 불가
            profile.is_profile_complete = False # ★ 핵심: 승인 후 로그인 시 2차 정보 기입 유도

            # [PL 자동 감지 로직 보존]
            try:
                pl_obj = PartLeader.objects.get(email=email)
                profile.is_pl = True
                profile.name = pl_obj.name # 이름 자동 입력
                
                # PL은 편의상 프로필 완료 처리
                profile.is_profile_complete = True 
                
                user.is_staff = True # 스태프 권한 부여
                user.save()
                
                msg = f"{pl_obj.name} 파트장님, 회원가입이 완료되었습니다. (관리자 승인 대기 중)"
            
            except PartLeader.DoesNotExist:
                # 일반 교육생
                msg = "회원가입이 완료되었습니다. 관리자 승인 후 이용 가능합니다."

            profile.save() # 변경사항 저장

            # PL(파트장) 가입이 아니라 일반 교육생 가입일 경우에만 매니저에게 알림!
            if not profile.is_pl:
                from quiz.models import Notification
                from django.urls import reverse
                from django.db.models import Q # (맨 위에 Q 임포트가 없다면 추가)
                
                # 매니저와 최고관리자 찾기
                managers = User.objects.filter(Q(profile__is_manager=True) | Q(is_superuser=True)).distinct()
                
                for manager in managers:
                    Notification.objects.create(
                        recipient=manager,
                        message=f"🔔 [신규 가입] {user.username}님의 승인 대기 중입니다.",
                        related_url=reverse('quiz:manager_trainee_list'), # 클릭 시 교육생 관리 창으로 이동
                        icon='bi-person-plus-fill',
                        notification_type='signup'
                    )
            # =========================================================
            
            # 👆 여기까지! 👆

            messages.success(request, msg)
            return redirect('accounts:login')
    else:
        form = CustomUserCreationForm()
    
    return render(request, 'accounts/signup.html', {'form': form})


# ---------------------------------------------------
# 2. 프로필 완성 (2차 정보 기입 - 강제)
# ---------------------------------------------------
@login_required
def complete_profile(request):
    try:
        profile = request.user.profile
    except Profile.DoesNotExist:
        # [수정됨] user 변수 오류 수정 (user -> request.user)
        profile = Profile.objects.create(user=request.user)

    # 이미 완료된 경우 리다이렉트
    if profile.is_profile_complete:
        if profile.is_pl: return redirect('quiz:pl_dashboard')
        if profile.is_manager: return redirect('quiz:manager_dashboard')
        return redirect('quiz:my_page')

    if request.method == 'POST':
        # ProfileForm 사용
        form = ProfileForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            profile.is_profile_complete = True
            profile.save()
            messages.success(request, "환영합니다! 프로필 설정이 완료되었습니다.")
            return redirect('quiz:my_page')
    else:
        form = ProfileForm(instance=profile)

    return render(request, 'accounts/complete_profile.html', {
        'profile_form': form, 
        'is_completing_profile': True
    })


# ---------------------------------------------------
# 3. 기타 유틸리티 및 뷰
# ---------------------------------------------------

def custom_logout(request):
    logout(request)
    return redirect('accounts:login')

@login_required
def profile_update(request):
    profile = request.user.profile
    
    if request.method == 'POST':
        # ProfileUpdateForm 사용
        form = ProfileUpdateForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, "프로필 정보가 수정되었습니다.")
            return redirect('quiz:my_page')
    else:
        form = ProfileUpdateForm(instance=profile)
        
    return render(request, 'accounts/profile_update.html', {
        'form': form,
        'info_msg': '※ 기수, 공정, 담당 PL 정보는 관리자만 수정 가능합니다.'
    })

def load_part_leaders(request):
    """
    [AJAX] 공정/회사 선택 시 해당 파트장 목록 반환
    """
    company_id = request.GET.get('company_id')
    process_id = request.GET.get('process_id')
    
    if not company_id or not process_id: 
        return JsonResponse({'pls': []})
    
    try:
        pls = PartLeader.objects.filter(company_id=company_id, process=process_id).order_by('name')
        return JsonResponse({'pls': [{"id": p.id, "name": p.name} for p in pls]})
    except Exception as e:
        print(f"❌ AJAX Error: {e}")
        return JsonResponse({'error': '데이터 로드 중 오류 발생'}, status=500)

def custom_login(request):
    """
    [커스텀 로그인 - 최종 완성]
    1. 관리자(Superuser, Staff, Manager, PL): 
       - 무조건 프리패스 (승인여부, 기수날짜, 상태 무시하고 로그인)
    2. 일반 교육생:
       - 승인 대기중 -> 로그인 차단 (메시지)
       - 기수 종료일 지남 -> '수료' 상태로 자동 변경 -> completed_alert.html (로그인 안됨)
       - 상태가 'dropout' -> dropout_alert.html (로그인 안됨)
       - 상태가 'counseling' -> counseling_required.html (로그인 안됨)
       - 정상(attending) -> 로그인 성공
    """
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        
        if form.is_valid():
            user = form.get_user()
            
            try:
                # 프로필 가져오기 (없으면 생성 - 안전장치)
                profile, created = Profile.objects.get_or_create(user=user)
                
                # =====================================================
                # 1. 관리자 권한 확인 (★ 가장 먼저 체크 - 프리패스)
                # =====================================================
                is_admin_user = (
                    user.is_superuser or 
                    user.is_staff or 
                    profile.is_manager or 
                    profile.is_pl
                )

                if is_admin_user:
                    # 관리자는 혹시 미승인 상태라도 강제 승인 후 로그인
                    if not profile.is_approved:
                        profile.is_approved = True
                        profile.save()
                    
                    auth_login(request, user)
                    
                    # 관리자 등급별 대시보드 이동
                    if user.is_superuser:
                        return redirect('quiz:manager_dashboard')  # 최종관리자 → /quiz/manager/
                    if profile.is_manager:
                        return redirect('quiz:manager_dashboard')  # 매니저 → /quiz/manager/
                    if profile.is_pl:
                        return redirect('quiz:pl_dashboard')  
                    if user.is_staff:
                        return redirect('quiz:manager_dashboard')  # staff도 매니저 페이지로
                    return redirect('quiz:my_page')                # 일반 교육생 → /quiz/student/

                # =====================================================
                # 2. 일반 교육생 체크 (여기서부터 깐깐하게 검사)
                # =====================================================
                
                # (A) 관리자 승인 여부 확인
                if not profile.is_approved:
                    messages.error(request, "⚠️ 가입 승인 대기 중입니다. 관리자 승인 후 이용 가능합니다.")
                    return render(request, 'accounts/login.html', {'form': form})

                # (B) 기수 기간 만료 체크 (자동 수료 처리 방지)
                if profile.cohort and profile.cohort.end_date:
                    today = timezone.now().date()
                    if profile.cohort.end_date < today:
                        # ★ [수정됨] 상태를 마음대로 'completed'로 바꾸지 않고, 
                        # 단순히 로그인만 차단(안내 페이지 렌더링)합니다.
                        # (상태는 매니저가 평가서를 작성해야만 바뀝니다)
                        return render(request, 'accounts/completed_alert.html', {'profile': profile})

                # (C) 상태별 분기 처리 (이미 DB에 저장된 상태 확인)
                if profile.status == 'completed':
                    # 이미 수료 상태인 경우
                    return render(request, 'accounts/completed_alert.html', {'profile': profile})
                
                elif profile.status == 'dropout':
                    # 퇴소 상태인 경우
                    return render(request, 'accounts/dropout_alert.html', {'profile': profile})
                
                elif profile.status == 'counseling':
                    # 상담 필요(잠금) 상태인 경우
                    return render(request, 'accounts/counseling_required.html', {'profile': profile})

                # =====================================================
                # 3. 모든 관문 통과 -> 정상 로그인 수행
                # =====================================================
                auth_login(request, user)

                # 2차 정보 기입 확인 (프로필 미완성 시 이동)
                if not profile.is_profile_complete:
                    return redirect('accounts:complete_profile')

                # 일반 학생 메인 페이지 이동
                return redirect('quiz:my_page')

            except Exception as e:
                print(f"Login Logic Error: {e}")
                messages.error(request, "로그인 처리 중 오류가 발생했습니다.")
                return render(request, 'accounts/login.html', {'form': form})
                
        else:
            # 아이디/비번 틀림
            return render(request, 'accounts/login.html', {'form': form})
            
    else:
        form = AuthenticationForm()

    return render(request, 'accounts/login.html', {'form': form})

from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm

@login_required
def custom_password_change(request):
    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            # 세션 유지 (비밀번호 바꾸고 튕기는 것 방지)
            update_session_auth_hash(request, user)
            
            # ★★★ [핵심] 족쇄 풀기! ★★★
            if hasattr(user, 'profile'):
                user.profile.must_change_password = False
                user.profile.save()
            
            messages.success(request, '비밀번호가 성공적으로 변경되었습니다.')
            return redirect('accounts:password_change_done') 
    else:
        form = PasswordChangeForm(request.user)
    
    return render(request, 'accounts/password_change_form.html', {'form': form})

# ---------------------------------------------------
# 4. 안내 페이지들
# ---------------------------------------------------
def counseling_required(request): return render(request, 'accounts/counseling_required.html')
def dropout_alert(request): return render(request, 'accounts/dropout_alert.html')
def completed_alert(request): return render(request, 'accounts/completed_alert.html')
def cohort_expired(request): return render(request, 'accounts/cohort_expired.html')