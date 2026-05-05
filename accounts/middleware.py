from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from .models import Profile
from django.contrib.auth import logout
from django.contrib import messages
from datetime import timedelta         
from django.http import JsonResponse

# [1] 비밀번호 강제 변경 미들웨어 (기존 유지)
class ForcePasswordChangeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            # 프로필 안전장치 (없으면 생성)
            if not hasattr(request.user, 'profile'):
                Profile.objects.create(user=request.user)
            
            profile = request.user.profile
            
            if hasattr(profile, 'password_updated_at') and profile.password_updated_at:
                if timezone.now() > profile.password_updated_at + timedelta(days=90):
                    profile.must_change_password = True
                    profile.save()

            # URL 이름이 실제 urls.py와 일치하는지 꼭 확인하세요!
            password_change_url = reverse('accounts:password_change')
            password_change_done_url = reverse('accounts:password_change_done')
            logout_url = reverse('accounts:logout')

            # 변경 완료 페이지면 플래그 해제
            if request.path == password_change_done_url:
                if profile.must_change_password:
                    profile.must_change_password = False

                    if hasattr(profile, 'password_updated_at'):
                        profile.password_updated_at = timezone.now()

                    profile.save()
                return self.get_response(request)

            # 변경해야 하는 상태면 강제 이동
            if profile.must_change_password:
                if request.path not in [password_change_url, password_change_done_url, logout_url]:
                    return redirect(password_change_url)

        response = self.get_response(request)
        return response


# [2] 계정 상태 및 접근 제어 통합 미들웨어 (통합됨)
class AccountStatusMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated and request.path.startswith('/quiz/api/'):
            from django.http import JsonResponse
            return JsonResponse({'error': 'not_logged_in'}, status=401)
        # 1. 로그인한 사용자만 검사
        if request.user.is_authenticated:
            
            # [예외 1] 관리자(Superuser) 및 스태프는 프리패스
            if request.user.is_superuser or request.user.is_staff:
                return self.get_response(request)
            
            # 프로필 로드 (안전장치)
            if not hasattr(request.user, 'profile'):
                Profile.objects.create(user=request.user)
            profile = request.user.profile

            # [예외 2] 운영진(Manager, PL) 프리패스
            if profile.is_manager or profile.is_pl:
                return self.get_response(request)

            # [예외 3] 비밀번호 변경 중이면 통과 (위 미들웨어와 충돌 방지)
            if profile.must_change_password:
                return self.get_response(request)

            # -------------------------------------------------------
            # [검사 1] 상태(Status) 기반 '사이트 접속 차단' (Render 방식)
            # -------------------------------------------------------
            status = profile.status
            current_path = request.path
            
            # 차단 상태에서도 접속해야 하는 필수 경로들
            allowed_paths = [
                reverse('accounts:logout'), # 로그아웃
                '/admin/',                  # 관리자 페이지
            ]
            
            # 현재 경로가 허용된 경로인지 확인
            is_allowed_path = any(current_path.startswith(path) for path in allowed_paths)

            if not is_allowed_path:
                # 1-1. 수료생 (접속 차단 -> 수료증 화면)
                if status == 'completed':
                    return render(request, 'accounts/completed_alert.html')

                # 1-2. 면담 필요 / 퇴소 (접속 차단 -> 경고 화면)
                # 퇴소자(dropout)도 일단 면담 화면을 보여주거나, 별도 dropout.html이 있다면 그것을 사용
                elif status in ['counseling', 'dropout']:
                    # 만약 퇴소 전용 페이지가 있다면: return render(request, 'accounts/dropout_alert.html')
                    # 현재는 면담 필요 페이지로 통합 처리
                    return render(request, 'accounts/counseling_required.html')

            # -------------------------------------------------------
            # [검사 2] 기수 기간 만료 체크 (Redirect 방식)
            # -------------------------------------------------------
            # 차단 상태가 아닐 때만(attending 등) 수행
            if status == 'attending' and profile.cohort and profile.cohort.end_date:
                today = timezone.now().date()
                expired_url = reverse('accounts:cohort_expired') # urls.py에 name='cohort_expired'가 있어야 함

                if today > profile.cohort.end_date:
                    if current_path not in [expired_url] + allowed_paths:
                        return redirect('accounts:cohort_expired')

            # -------------------------------------------------------
            # [검사 3] 프로필 미완성 체크 (Redirect 방식)
            # -------------------------------------------------------
            if status == 'attending' and not profile.is_profile_complete:
                complete_profile_url = reverse('accounts:complete_profile')
                # Ajax 요청 등은 통과시켜야 함
                ajax_pl_url = reverse('accounts:ajax_load_part_leaders') if 'accounts:ajax_load_part_leaders' in str(reverse) else '/accounts/ajax/' 

                # 예외 경로 추가 (프로필 완성 페이지, 로그아웃 등)
                profile_allowed = allowed_paths + [complete_profile_url, ajax_pl_url]
                
                is_profile_path = any(current_path.startswith(p) for p in profile_allowed)
                
                # 비밀번호 초기화 관련 URL도 허용
                if not is_profile_path:
                    if not (current_path.startswith('/accounts/password_reset/') or 
                            current_path.startswith('/accounts/reset/')):
                        return redirect('accounts:complete_profile')

        response = self.get_response(request)
        return response

class ConcurrentLoginMiddleware:
    """중복 로그인을 감지하고 친절하게 안내 문구를 띄우며 쫓아내는 문지기"""
    
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 1. 로그인한 사용자이고, 프로필이 있는 경우에만 검사
        if request.user.is_authenticated and hasattr(request.user, 'profile'):
            
            # 내 손에 들려있는 접속증 번호 vs DB에 기록된 가장 최신 접속증 번호
            current_key = request.session.session_key
            valid_key = request.user.profile.session_key

            # 2. 내 번호와 DB의 최신 번호가 다르다? -> 누군가 다른 곳에서 로그인해서 내 접속증을 뺏어갔다!
            if current_key and valid_key and current_key != valid_key:
                
                if request.path.startswith('/quiz/api/'):
                    return JsonResponse({'error': 'concurrent_login'}, status=401)
                
                # (기존 코드) 일반적인 짐 싸서 내보냄
                logout(request) 
                messages.error(request, "⚠️ 다른 기기(또는 브라우저)에서 로그인이 감지되어 안전하게 자동 로그아웃 되었습니다.")
                return redirect('accounts:login') 

        return self.get_response(request)