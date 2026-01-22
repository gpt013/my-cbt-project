# quiz/middleware.py

from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.contrib import messages

class StudentAccessControlMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 1. 로그인하지 않은 유저는 통과 (LoginRequired가 알아서 막음)
        if not request.user.is_authenticated:
            return self.get_response(request)

        # 2. 관리자(Staff/Superuser)는 무조건 프리패스
        if request.user.is_staff or request.user.is_superuser:
            return self.get_response(request)

        # 3. 프로필 확인
        if not hasattr(request.user, 'profile'):
            return self.get_response(request)

        profile = request.user.profile
        path = request.path

        # [면제 경로] 이 경로들은 차단되면 안 됨 (로그아웃, 정적파일 등)
        exempt_urls = [
            reverse('accounts:logout'),
            '/static/',
            '/media/',
            '/admin/',
        ]
        
        # 현재 접속하려는 곳이 면제 경로인지 확인
        if any(path.startswith(url) for url in exempt_urls):
            return self.get_response(request)

        # -----------------------------------------------------------
        # [A] 퇴소자 (Dropout) 처리
        # -----------------------------------------------------------
        if profile.status == 'dropout':
            today = timezone.now().date()
            cohort_end = profile.cohort.end_date if profile.cohort else None

            # A-1. 기수 기간이 아직 남았을 때 -> counseling_required (퇴소 안내/면담)
            # (기수가 없거나, 종료일이 오늘보다 미래인 경우)
            if not cohort_end or cohort_end >= today:
                target_url = reverse('quiz:counseling_required')
                if path != target_url:
                    return redirect(target_url)
            
            # A-2. 기수 기간이 끝났을 때 -> dropout_alert (최종 퇴소 확정)
            else:
                target_url = reverse('quiz:dropout_alert')
                if path != target_url:
                    return redirect(target_url)

        # -----------------------------------------------------------
        # [B] 수료자 (Completed) 처리 - [수정됨]
        # -----------------------------------------------------------
        elif profile.status == 'completed':
            today = timezone.now().date()
            cohort_end = profile.cohort.end_date if (profile.cohort and profile.cohort.end_date) else None

            # [핵심 로직 변경]
            # 기수 종료일이 존재하고, 오늘 날짜가 종료일을 지났을 때만 -> 수료증 페이지로 납치
            if cohort_end and today > cohort_end:
                target_url = reverse('quiz:completed_alert')
                if path != target_url:
                    return redirect(target_url)
            
            # 아직 기수 기간이 남았거나(오늘 포함), 종료일이 설정 안 된 경우 
            # -> 정상적으로 대시보드 접속 허용 (통과)
            else:
                return self.get_response(request)

        # -----------------------------------------------------------
        # [C] 주의/면담필요 (Counseling) 처리 - (옵션: 선택사항)
        # -----------------------------------------------------------
        # 만약 'counseling' 상태(시험 불합격 잠금 등)일 때도 막고 싶다면 주석 해제
        # elif profile.status == 'counseling':
        #     target_url = reverse('quiz:counseling_required')
        #     if path != target_url:
        #         return redirect(target_url)

        return self.get_response(request)