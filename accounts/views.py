from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import logout, login, authenticate
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from django.http import JsonResponse
from django.db.models import Sum, Count, Q
import random

# forms.py에서 정의한 폼들 import
from .forms import CustomUserCreationForm, ProfileForm, EmailVerificationForm, ProfileUpdateForm
# models.py에서 정의한 모델들 import
from .models import PartLeader, Profile, EmailVerification


# ---------------------------------------------------
# [Helper] 이메일 발송 내부 함수 (성공 여부 반환)
# ---------------------------------------------------
def _send_verification_email(request, user):
    """
    인증 코드를 생성하고 이메일로 발송합니다.
    성공 시 True, 실패 시 False를 반환합니다.
    """
    verification_code = str(random.randint(100000, 999999))
    
    # 기존 코드 삭제 후 생성 (최신 코드만 유지)
    EmailVerification.objects.filter(email=user.email).delete()
    EmailVerification.objects.create(email=user.email, code=verification_code)

    subject = '[PMTC] 회원가입 인증 코드 안내'
    message = f'안녕하세요. 회원가입 인증 코드는 [{verification_code}] 입니다.\n5분 안에 입력해주세요.'
    
    try:
        send_mail(subject, message, settings.EMAIL_HOST_USER, [user.email], fail_silently=False)
        
        # 세션에 중요 정보 저장 (인증 페이지에서 사용)
        request.session['signup_email'] = user.email
        request.session['signup_user_id'] = user.id
        return True
        
    except Exception as e:
        print(f"❌ 이메일 발송 실패: {e}")
        messages.error(request, "메일 서버 오류로 인증 코드를 보낼 수 없습니다. 이메일 주소를 확인해주세요.")
        return False


# ---------------------------------------------------
# 1. 회원가입 (OTP 발송 및 중복 처리 개선)
# ---------------------------------------------------
def signup(request):
    if request.user.is_authenticated:
        return redirect('quiz:my_page')

    if request.method == 'POST':
        # [핵심] 이메일 중복 및 상태 먼저 확인
        email = request.POST.get('email')
        existing_user = User.objects.filter(email=email).first()

        if existing_user:
            # (A) 이미 활동 중인 유저 -> 로그인 유도
            if existing_user.is_active:
                messages.error(request, "이미 가입 완료된 계정입니다. 로그인해주세요.")
                return redirect('accounts:login')
            
            # (B) 가입 시도했으나 미인증 상태 -> 재발송 후 인증 페이지로
            else:
                if _send_verification_email(request, existing_user):
                    messages.info(request, "인증이 완료되지 않은 계정입니다. 인증 코드를 다시 발송했습니다.")
                    return redirect('accounts:verify_email')
                else:
                    return redirect('accounts:signup') # 발송 실패 시 다시 가입 화면

        # (C) 신규 가입
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.is_active = False # 인증 전까지 비활성화
            user.save()

            # 인증 코드 발송
            if _send_verification_email(request, user):
                return redirect('accounts:verify_email')
            else:
                # 발송 실패 시 유저 삭제 (롤백)
                user.delete()
                return redirect('accounts:signup')
    else:
        form = CustomUserCreationForm()
    
    return render(request, 'accounts/signup.html', {'form': form})


# ---------------------------------------------------
# 2. 이메일 인증 및 PL 자동 감지
# ---------------------------------------------------
def verify_email(request):
    email = request.session.get('signup_email')
    user_id = request.session.get('signup_user_id')

    if not email:
        messages.error(request, "잘못된 접근입니다. 회원가입을 다시 진행해주세요.")
        return redirect('accounts:signup')

    if request.method == 'POST':
        form = EmailVerificationForm(request.POST)
        if form.is_valid():
            code = form.cleaned_data['code']
            verification = EmailVerification.objects.filter(email=email).last()

            if verification and verification.code == code:
                if verification.is_expired():
                    messages.error(request, "인증 시간이 만료되었습니다. [코드 재전송]을 눌러주세요.")
                else:
                    # [인증 성공]
                    try:
                        user = User.objects.get(pk=user_id)
                        user.is_active = True
                        user.save()
                        
                        # PL(파트장) 자동 등업 로직
                        try:
                            pl_obj = PartLeader.objects.get(email=email)
                            user.profile.is_pl = True
                            user.profile.is_profile_complete = True # PL은 프로필 설정 패스
                            user.profile.name = pl_obj.name
                            user.profile.save()
                            
                            user.is_staff = True # 대시보드 접근 권한
                            user.save()
                            
                            messages.success(request, f"{pl_obj.name} 파트장님, 환영합니다! (PL 권한 부여됨)")
                            
                            # 인증 기록 사용 처리
                            verification.is_verified = True
                            verification.save()
                            
                            login(request, user)
                            return redirect('quiz:pl_dashboard') # PL 대시보드로 직행

                        except PartLeader.DoesNotExist:
                            # 일반 교육생
                            messages.success(request, "이메일 인증이 완료되었습니다. 이제 프로필을 완성해주세요.")
                        
                        # 인증 기록 사용 처리
                        verification.is_verified = True
                        verification.save()
                        
                        login(request, user)
                        return redirect('accounts:complete_profile') # 일반 유저는 프로필 설정으로

                    except User.DoesNotExist:
                        messages.error(request, "사용자 정보를 찾을 수 없습니다. 다시 가입해주세요.")
                        return redirect('accounts:signup')
            else:
                messages.error(request, "인증 코드가 올바르지 않습니다.")
    else:
        form = EmailVerificationForm()

    return render(request, 'accounts/verify_email.html', {'form': form, 'email': email})


# ---------------------------------------------------
# [신규] 인증 코드 재발송
# ---------------------------------------------------
def resend_code(request):
    email = request.session.get('signup_email')
    user_id = request.session.get('signup_user_id')
    
    if not email or not user_id:
        messages.error(request, "가입 정보가 없습니다. 다시 가입해주세요.")
        return redirect('accounts:signup')
        
    try:
        user = User.objects.get(pk=user_id)
        if _send_verification_email(request, user):
            messages.success(request, "인증 코드가 재발송되었습니다. 메일함을 확인해주세요.")
        else:
            # _send_verification_email 내부에서 이미 에러 메시지를 띄움
            pass
    except User.DoesNotExist:
        messages.error(request, "사용자를 찾을 수 없습니다.")
        
    return redirect('accounts:verify_email')


# ---------------------------------------------------
# 3. 프로필 완성 (강제)
# ---------------------------------------------------
@login_required
def complete_profile(request):
    profile = request.user.profile
    
    # 이미 완료된 경우 리다이렉트
    if profile.is_profile_complete:
        if profile.is_pl: return redirect('quiz:pl_dashboard')
        if profile.is_manager: return redirect('quiz:manager_dashboard')
        return redirect('quiz:my_page')

    if request.method == 'POST':
        # [수정] ProfileForm 사용 (가입 초기에는 모든 정보 입력 가능)
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
# 4. 기타 유틸리티 및 뷰
# ---------------------------------------------------

def custom_logout(request):
    logout(request)
    return redirect('accounts:login')

@login_required
def profile_update(request):
    profile = request.user.profile
    
    if request.method == 'POST':
        # [수정] ProfileUpdateForm 사용 (수정 시에는 민감 정보 변경 불가)
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
    company_id = request.GET.get('company_id')
    process_id = request.GET.get('process_id')
    
    if not company_id or not process_id: 
        return JsonResponse({'pls': []})
    
    try:
        pls = PartLeader.objects.filter(company_id=company_id, process_id=process_id).order_by('name')
        return JsonResponse({'pls': [{"id": p.id, "name": p.name} for p in pls]})
    except Exception as e:
        print(f"❌ AJAX Error: {e}")
        return JsonResponse({'error': '데이터 로드 중 오류 발생'}, status=500)

# 안내 페이지들
def counseling_required(request): return render(request, 'accounts/counseling_required.html')
def dropout_alert(request): return render(request, 'accounts/dropout_alert.html')
def completed_alert(request): return render(request, 'accounts/completed_alert.html')
def cohort_expired(request): return render(request, 'accounts/cohort_expired.html')