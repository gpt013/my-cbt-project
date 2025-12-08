from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import logout, login, authenticate
from django.contrib.auth.models import User
from django.contrib import messages
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
import random, holidays
from django.db import transaction
from .forms import CustomUserCreationForm, ProfileForm, EmailVerificationForm
from django.http import JsonResponse
from .models import PartLeader, Profile, EmailVerification
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count, Q

# ---------------------------------------------------
# [Helper] 이메일 발송 내부 함수
# ---------------------------------------------------
def _send_verification_email(request, user):
    verification_code = str(random.randint(100000, 999999))
    
    # 기존 코드 삭제 후 생성
    EmailVerification.objects.filter(email=user.email).delete()
    EmailVerification.objects.create(email=user.email, code=verification_code)

    subject = '[PMTC] 회원가입 인증 코드 안내'
    message = f'안녕하세요. 회원가입 인증 코드는 [{verification_code}] 입니다.\n5분 안에 입력해주세요.'
    
    try:
        send_mail(subject, message, settings.EMAIL_HOST_USER, [user.email], fail_silently=False)
        # 세션에 정보 저장
        request.session['signup_email'] = user.email
        request.session['signup_user_id'] = user.id
    except Exception as e:
        print(f"이메일 발송 실패: {e}")
        messages.error(request, "메일 발송 중 오류가 발생했습니다. 이메일 주소를 확인해주세요.")

# ---------------------------------------------------
# 1. 회원가입 (OTP 발송)
# ---------------------------------------------------
def signup(request):
    if request.user.is_authenticated:
        return redirect('quiz:my_page')

    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            # 이메일 중복 체크 (이미 가입된 유저인지)
            email = form.cleaned_data.get('email')
            if User.objects.filter(email=email).exists():
                messages.error(request, "이미 가입된 이메일입니다.")
                return render(request, 'accounts/signup.html', {'form': form})

            user = form.save(commit=False)
            user.is_active = False # 인증 전 비활성화
            user.save()

            # 인증 코드 발송 로직
            _send_verification_email(request, user)
            
            return redirect('accounts:verify_email')
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
                    # 인증 성공
                    try:
                        user = User.objects.get(pk=user_id)
                        user.is_active = True
                        user.save()
                        
                        # PL 자동 등업
                        if PartLeader.objects.filter(email=email).exists():
                            user.profile.is_pl = True
                            user.profile.save()
                            messages.success(request, "파트장(PL) 계정으로 확인되어 권한이 부여되었습니다! 🎉")
                        else:
                            messages.success(request, "이메일 인증이 완료되었습니다. 이제 프로필을 완성해주세요.")
                        
                        # 인증 기록 사용 처리
                        verification.is_verified = True
                        verification.save()
                        
                        login(request, user)
                        return redirect('accounts:complete_profile')

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
        _send_verification_email(request, user)
        messages.success(request, "인증 코드가 재발송되었습니다. 메일함을 확인해주세요.")
    except User.DoesNotExist:
        messages.error(request, "사용자를 찾을 수 없습니다.")
        
    return redirect('accounts:verify_email')

# ---------------------------------------------------
# 3. 프로필 완성 (강제)
# ---------------------------------------------------
@login_required
def complete_profile(request):
    profile = request.user.profile
    if profile.is_profile_complete:
        return redirect('quiz:my_page')

    if request.method == 'POST':
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
        form = ProfileForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, "프로필 정보가 성공적으로 수정되었습니다.")
            return redirect('quiz:my_page')
    else:
        form = ProfileForm(instance=profile)
    return render(request, 'accounts/profile_update.html', {'form': form})

def load_part_leaders(request):
    company_id = request.GET.get('company_id')
    process_id = request.GET.get('process_id')
    if not company_id or not process_id: return JsonResponse({'pls': []})
    
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