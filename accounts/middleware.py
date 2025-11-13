# accounts/middleware.py

from django.shortcuts import redirect
from django.urls import reverse
from .models import Profile # Profile 모델을 import

class ProfileCompletionMiddleware:
    """
    로그인한 사용자가 프로필을 완성했는지 매번 검사하는 미들웨어.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        
        # 1. 로그인 상태이고, 스태프(관리자)가 아닌 경우에만 검사
        if request.user.is_authenticated and not request.user.is_staff:
            
            # 2. (안전장치) 프로필이 있는지 확인 (없으면 생성)
            if not hasattr(request.user, 'profile'):
                Profile.objects.create(user=request.user)
            
            # 3. '프로필 완성' 플래그가 False인지 확인
            if not request.user.profile.is_profile_complete:
                
                # --- [핵심 수정] ---
                # 4. 강제이동 예외 목록에 AJAX URL을 추가합니다.
                allowed_paths = [
                    reverse('accounts:complete_profile'),       # 1. 프로필 완성 페이지 (필수)
                    reverse('accounts:logout'),               # 2. 로그아웃 (필수)
                    reverse('accounts:ajax_load_part_leaders') # 3. [이 줄 추가] PL 로딩 AJAX
                ]
                # ------------------
                
                # 5. 현재 경로가 예외 목록에 없다면, 강제로 프로필 완성 페이지로 보냄
                if request.path not in allowed_paths:
                    # (비밀번호 재설정 관련 URL도 예외에 추가)
                    if request.path.startswith('/accounts/password_reset/') or \
                       request.path.startswith('/accounts/reset/'):
                        pass # 비밀번호 재설정 중에는 통과
                    else:
                        return redirect('accounts:complete_profile')
        
        # (위 조건에 해당하지 않으면 정상 진행)
        response = self.get_response(request)
        return response