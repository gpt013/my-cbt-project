from django.shortcuts import redirect
from django.urls import reverse
from .models import Profile

# [1] 비밀번호 강제 변경 미들웨어 (1순위 검사)
class ForcePasswordChangeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            # 안전장치: 프로필 없으면 생성
            if not hasattr(request.user, 'profile'):
                Profile.objects.create(user=request.user)
            
            profile = request.user.profile
            
            # ▼▼▼ [핵심 수정] 납치 장소를 'admin' -> 'accounts'(우리가 만든 곳)로 변경 ▼▼▼
            password_change_url = reverse('accounts:password_change')
            password_change_done_url = reverse('accounts:password_change_done')
            logout_url = reverse('accounts:logout') # (로그아웃 URL도 확인 필요)
            # ▲▲▲ ----------------------------------------------------------- ▲▲▲

            # [A] 변경 완료 페이지 도착 -> 플래그 해제
            if request.path == password_change_done_url:
                if profile.must_change_password:
                    profile.must_change_password = False
                    profile.save()
                return self.get_response(request)

            # [B] 강제 변경 켜져 있으면 -> 납치
            if profile.must_change_password:
                # 허용된 곳이 아니면 무조건 변경 페이지로 리다이렉트
                if request.path not in [password_change_url, password_change_done_url, logout_url]:
                    return redirect(password_change_url)

        response = self.get_response(request)
        return response


# [2] 계정 상태 통합 관리 미들웨어 (2순위 - 통합/강화됨)
# (기존 ProfileCompletionMiddleware를 대체합니다)
class AccountStatusMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 로그인 상태이고, 관리자(Staff)가 아닌 경우에만 검사
        if request.user.is_authenticated and not request.user.is_staff:
            
            if not hasattr(request.user, 'profile'):
                Profile.objects.create(user=request.user)
            
            profile = request.user.profile

            # (A) 비밀번호 변경 중이면 통과 (1순위 미들웨어가 처리함)
            if profile.must_change_password:
                return self.get_response(request)

            # -------------------------------------------------------
            # [검사 1] 상태(Status) 체크 : 면담필요 / 퇴소 납치
            # -------------------------------------------------------
            status = profile.status
            current_path = request.path
            
            # 허용된 예외 URL (로그아웃은 언제나 가능해야 함)
            logout_url = reverse('accounts:logout')
            counseling_url = reverse('accounts:counseling_required')
            dropout_url = reverse('accounts:dropout_alert')

            # 1-1. 면담 필요 (counseling)
            if status == 'counseling':
                # 이미 대기실에 있거나 로그아웃 중이면 통과, 아니면 납치
                if current_path not in [counseling_url, logout_url]:
                    return redirect('accounts:counseling_required')
            
            # 1-2. 퇴소 (dropout)
            elif status == 'dropout':
                if current_path not in [dropout_url, logout_url]:
                    return redirect('accounts:dropout_alert')
            # ▼▼▼ [추가] 1-3. 수료 (completed) - 접속 차단 ▼▼▼
            elif status == 'completed':
                completed_url = reverse('accounts:completed_alert')
                if current_path not in [completed_url, logout_url]:
                    return redirect('accounts:completed_alert')

            # -------------------------------------------------------
            # [검사 2] 프로필 완성 여부 체크 (기존 기능)
            # -------------------------------------------------------
            if not profile.is_profile_complete:
                complete_profile_url = reverse('accounts:complete_profile')
                ajax_pl_url = reverse('accounts:ajax_load_part_leaders')
                
                # 상태가 정상이지만 프로필이 미완성이면 납치
                if status == 'attending':
                    if current_path not in [complete_profile_url, logout_url, ajax_pl_url]:
                        # 비밀번호 재설정 URL 예외 처리
                        if not (current_path.startswith('/accounts/password_reset/') or 
                                current_path.startswith('/accounts/reset/')):
                            return redirect('accounts:complete_profile')

        response = self.get_response(request)
        return response