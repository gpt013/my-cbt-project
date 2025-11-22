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


# [2] 프로필 완성 검사 미들웨어 (2순위 검사)
class ProfileCompletionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 로그인 상태이고, 스태프(관리자)가 아닌 경우에만 검사
        if request.user.is_authenticated and not request.user.is_staff:
            
            # 프로필이 없으면 생성
            if not hasattr(request.user, 'profile'):
                Profile.objects.create(user=request.user)
            
            profile = request.user.profile

            # [중요] 비밀번호 강제 변경 중이라면, 프로필 검사는 건너뜀 (비밀번호가 먼저임)
            if profile.must_change_password:
                return self.get_response(request)

            # '프로필 완성' 플래그가 False인지 확인
            if not profile.is_profile_complete:
                
                # 예외 URL 목록
                allowed_paths = [
                    reverse('accounts:complete_profile'),        # 프로필 완성 페이지
                    reverse('accounts:logout'),                  # 로그아웃
                    reverse('accounts:ajax_load_part_leaders'),  # PL 로딩 AJAX
                    # 비밀번호 변경 관련 URL도 허용해줘야 충돌이 안 남
                    reverse('admin:password_change'),
                    reverse('admin:password_change_done'),
                ]
                
                # 현재 경로가 예외 목록에 없고, 비밀번호 관련도 아니라면 -> 강제 이동
                if request.path not in allowed_paths:
                    # 추가적인 안전장치 (URL 시작 부분 검사)
                    if not (request.path.startswith('/accounts/password_reset/') or 
                            request.path.startswith('/accounts/reset/')):
                        return redirect('accounts:complete_profile')
        
        response = self.get_response(request)
        return response