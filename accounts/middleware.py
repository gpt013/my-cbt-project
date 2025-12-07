from django.shortcuts import redirect, render # [필수] render 추가됨
from django.urls import reverse
from django.utils import timezone
from .models import Profile

# [1] 비밀번호 강제 변경 미들웨어
class ForcePasswordChangeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            if not hasattr(request.user, 'profile'):
                Profile.objects.create(user=request.user)
            
            profile = request.user.profile
            
            password_change_url = reverse('accounts:password_change')
            password_change_done_url = reverse('accounts:password_change_done')
            logout_url = reverse('accounts:logout')

            if request.path == password_change_done_url:
                if profile.must_change_password:
                    profile.must_change_password = False
                    profile.save()
                return self.get_response(request)

            if profile.must_change_password:
                if request.path not in [password_change_url, password_change_done_url, logout_url]:
                    return redirect(password_change_url)

        response = self.get_response(request)
        return response


# [2] 계정 상태 통합 관리 미들웨어
class AccountStatusMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 로그인 상태이고, 관리자/스태프/PL이 아닌 '일반 교육생'만 검사
        if request.user.is_authenticated:
            
            # [운영진 프리패스] 관리자나 PL은 상태 검사를 건너뜁니다.
            if request.user.is_superuser or request.user.is_staff:
                return self.get_response(request)
            
            if not hasattr(request.user, 'profile'):
                Profile.objects.create(user=request.user)
            profile = request.user.profile

            if profile.is_manager or profile.is_pl:
                return self.get_response(request)

            # (A) 비밀번호 변경 중이면 통과
            if profile.must_change_password:
                return self.get_response(request)

            # -------------------------------------------------------
            # [검사 1] 상태(Status) 체크 : 면담필요 / 퇴소 / 수료 납치
            # -------------------------------------------------------
            status = profile.status
            current_path = request.path
            
            logout_url = reverse('accounts:logout')
            counseling_url = reverse('accounts:counseling_required')
            dropout_url = reverse('accounts:dropout_alert')
            completed_url = reverse('accounts:completed_alert')
            expired_url = reverse('accounts:cohort_expired') # URL name 확인 필요

            # 1-1. 면담 필요
            if status == 'counseling':
                if current_path not in [counseling_url, logout_url]:
                    return redirect('accounts:counseling_required')
            
            # 1-2. 퇴소
            elif status == 'dropout':
                if current_path not in [dropout_url, logout_url]:
                    return redirect('accounts:dropout_alert')

            # 1-3. 수료
            elif status == 'completed':
                if current_path not in [completed_url, logout_url]:
                    return redirect('accounts:completed_alert')

            # -------------------------------------------------------
            # [검사 2] 기수 기간 만료 체크
            # -------------------------------------------------------
            if profile.cohort and profile.cohort.end_date:
                today = timezone.now().date()
                if today > profile.cohort.end_date:
                    # 만료 페이지나 로그아웃이 아니면 차단
                    # [주의] 여기서는 redirect가 아니라 render를 쓰거나, 별도 URL로 redirect 해야 합니다.
                    # 여기서는 URL로 redirect 하는 것이 깔끔하므로 redirect를 사용하되, 
                    # 해당 뷰에서 render하도록 처리합니다. (기존 views.py에 cohort_expired 뷰가 있어야 함)
                    if current_path not in [expired_url, logout_url]:
                        return redirect('accounts:cohort_expired') 

            # -------------------------------------------------------
            # [검사 3] 프로필 완성 여부 체크
            # -------------------------------------------------------
            if not profile.is_profile_complete:
                complete_profile_url = reverse('accounts:complete_profile')
                ajax_pl_url = reverse('accounts:ajax_load_part_leaders')
                
                # 상태가 정상(attending)일 때만 체크
                if status == 'attending':
                    if current_path not in [complete_profile_url, logout_url, ajax_pl_url, expired_url]:
                        if not (current_path.startswith('/accounts/password_reset/') or 
                                current_path.startswith('/accounts/reset/')):
                            return redirect('accounts:complete_profile')

        response = self.get_response(request)
        return response