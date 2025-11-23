# accounts/views.py (수정 완료)

from django.shortcuts import render, redirect
from django.contrib.auth import logout,login, authenticate
from django.contrib.auth.models import User
from django.contrib import messages
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
import random
from django.db import transaction
from .forms import CustomUserCreationForm, ProfileForm,EmailVerificationForm
from django.http import JsonResponse
# --- [핵심 1] import 수정 ---
from .models import PartLeader, Profile, EmailVerification
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

# 1. 회원가입 (OTP 발송)
def signup(request):
    if request.user.is_authenticated:
        return redirect('quiz:index')

    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.is_active = False # 인증 전 비활성화
            user.save()

            # 1) 인증 코드 생성
            verification_code = str(random.randint(100000, 999999))
            
            # 2) [수정] DB에 저장 (중복 에러 방지 로직)
            # 기존에 이 이메일로 된 인증 번호가 있다면 삭제합니다.
            EmailVerification.objects.filter(email=user.email).delete()
            
            # 그 다음 새로 만듭니다.
            EmailVerification.objects.create(
                email=user.email,
                code=verification_code
            )

            # 3) 이메일 발송 (콘솔 로그 확인용)
            subject = '[CBT] 회원가입 인증 코드 안내'
            message = f'안녕하세요. 회원가입 인증 코드는 [{verification_code}] 입니다.\n5분 안에 입력해주세요.'
            try:
                send_mail(subject, message, settings.EMAIL_HOST_USER, [user.email])
            except Exception as e:
                print(f"이메일 발송 실패: {e}")

            # 4) [핵심 수정] 이메일뿐만 아니라 '고유 ID(pk)'를 저장합니다.
            request.session['signup_email'] = user.email
            request.session['signup_user_id'] = user.id  # <--- 이게 있어야 중복 에러가 안 납니다!
            
            return redirect('accounts:verify_email')
    else:
        form = CustomUserCreationForm()
    
    return render(request, 'accounts/signup.html', {'form': form})


# 2. 이메일 인증 및 PL 자동 감지
def verify_email(request):
    email = request.session.get('signup_email')
    user_id = request.session.get('signup_user_id') # [추가] ID 가져오기

    # 세션 정보가 없으면 가입부터 다시
    if not email:
        messages.error(request, "잘못된 접근입니다. 회원가입을 다시 진행해주세요.")
        return redirect('accounts:signup')

    if request.method == 'POST':
        form = EmailVerificationForm(request.POST)
        if form.is_valid():
            code = form.cleaned_data['code']
            
            # 인증 정보 조회
            verification = EmailVerification.objects.filter(email=email).last()

            if verification and verification.code == code:
                if verification.is_expired():
                    messages.error(request, "인증 시간이 만료되었습니다. 다시 가입해주세요.")
                    return redirect('accounts:signup')
                
                # [성공] 사용자 활성화
                try:
                    # [핵심 수정] 이메일 대신 ID로 찾거나, 없으면 이메일로 찾되 최신 가입자를 선택
                    if user_id:
                        user = User.objects.get(pk=user_id)
                    else:
                        # 혹시 세션에 ID가 없으면(구버전), 이메일로 찾되 '가장 최근 가입자' 1명만 가져옴
                        user = User.objects.filter(email=email).order_by('-date_joined').first()

                    if not user:
                        raise User.DoesNotExist

                    user.is_active = True
                    user.save()
                    
                    # PL 자동 등업 로직
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
    process_id = request.GET.get('process_id')

    if not company_id or not process_id:
        return JsonResponse({'pls': []})

    try:
        # [보안 및 로직 수정] 
        # 1. ID 기반 필터링으로 정확도 향상
        # 2. 예외 처리 강화
        pls = PartLeader.objects.filter(
            company_id=company_id, 
            process_id=process_id  
        ).order_by('name')
        
        pl_list = [{"id": pl.id, "name": pl.name} for pl in pls]
        return JsonResponse({'pls': pl_list})
        
    except Exception as e:
        # [보안 핵심] 내부 에러 상세 내용(e)은 서버 로그에만 기록
        print(f"❌ AJAX Error (load_part_leaders): {e}")
        
        # 사용자에게는 일반적인 메시지만 전달하여 정보 유출 방지
        return JsonResponse({
            'error': '데이터를 불러오는 중 서버 오류가 발생했습니다. 관리자에게 문의하세요.'
        }, status=500)

def custom_logout(request):
    """
    GET 방식 로그아웃 허용 (Django 5.0 이상 대응)
    """
    logout(request) # 세션 삭제
    return redirect('accounts:login') # 로그인 페이지로 이동

# [신규] 계정 잠금(면담 필요) 안내 페이지
def counseling_required(request):
    return render(request, 'accounts/counseling_required.html')

# [신규] 퇴소 안내 페이지
def dropout_alert(request):
    return render(request, 'accounts/dropout_alert.html')
# 수료 안내 페이지
def completed_alert(request):
    return render(request, 'accounts/completed_alert.html')

@login_required
def profile_update(request):
    profile = request.user.profile
    
    if request.method == 'POST':
        # 기존 프로필 정보를 가져와서 수정
        form = ProfileForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, "프로필 정보가 성공적으로 수정되었습니다.")
            return redirect('quiz:my_page')
    else:
        # 기존 정보를 폼에 채워서 보여줌
        form = ProfileForm(instance=profile)

    return render(request, 'accounts/profile_update.html', {'form': form})