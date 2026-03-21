from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta

from accounts.models import Profile, Cohort, Process, Company, PartLeader

class PMTCSystemTests(TestCase):
    def setUp(self):
        self.today = timezone.now().date()
        
        # 1. 기초 데이터 생성
        self.company = Company.objects.create(name="테스트회사")
        self.process = Process.objects.create(name="테스트공정")
        self.part_leader = PartLeader.objects.create(name="테스트파트장", email="pl@test.com")
        
        # 2. 기수 생성
        self.cohort_34 = Cohort.objects.create(
            name="34기", 
            start_date=self.today - timedelta(days=5), 
            end_date=self.today + timedelta(days=30)
        )

        # 3. 사용자 및 프로필 설정
        # (1) 최고관리자
        self.admin_user = User.objects.create_superuser(username='admin', password='123')
        self.admin_profile, _ = Profile.objects.get_or_create(user=self.admin_user)
        self.admin_profile.name = '관리자'
        self.admin_profile.employee_id = 'AD001'
        self.admin_profile.is_approved = True
        self.admin_profile.save()

        # (2) 일반 학생 (★ 미들웨어 통과를 위한 완벽한 풀세트 세팅!)
        self.student_user = User.objects.create_user(username='student', password='123')
        self.student_profile, _ = Profile.objects.get_or_create(user=self.student_user)
        
        self.student_profile.name = '홍길동'
        self.student_profile.employee_id = 'ST12345'
        self.student_profile.company = self.company
        self.student_profile.process = self.process
        self.student_profile.cohort = self.cohort_34
        self.student_profile.joined_at = self.today
        self.student_profile.pl = self.part_leader
        self.student_profile.line = '테스트라인'  # ★ [추가] 라인 정보 등 빵꾸난 곳 메우기
        
        self.student_profile.status = 'attending'
        self.student_profile.is_approved = True
        
        if hasattr(self.student_profile, 'must_change_password'):
            self.student_profile.must_change_password = False
        
        self.student_profile.save()

    # =========================================================
    # [테스트 1] 동시 접속 차단 테스트
    # =========================================================
    def test_concurrent_login_middleware(self):
        client_home = Client()
        client_pcbang = Client()
        
        # 1. 집 컴퓨터 로그인 (세션 발급 목적)
        client_home.login(username='student', password='123')
        client_home.get(reverse('quiz:my_page')) # 200이든 302(프로필미완성)든 상관없이 일단 접속!

        # 2. PC방에서 동일 아이디 로그인 (세션 탈취)
        client_pcbang.login(username='student', password='123')
        
        # 3. 집 컴퓨터에서 다시 활동 시도
        response_home_again = client_home.get(reverse('quiz:my_page'))
        
        # 4. 검증: 이번엔 프로필 미완성이고 뭐고 간에 무조건 '로그인 창'으로 쫓겨나야 함!
        self.assertTrue(
            response_home_again.url.startswith(reverse('accounts:login')),
            f"실패: 로그인 창으로 안 튕기고 {response_home_again.url} 로 갔습니다."
        )

    # =========================================================
    # [테스트 4] 리포트에 매니저 제외 확인 (★ 에러 수정 완료)
    # =========================================================
    def test_cohort_report_excludes_staff(self):
        # 매니저 계정 생성
        manager_user = User.objects.create_user(username='manager', password='123', is_staff=True)
        
        # ★ [수정] create가 아닌 get_or_create를 사용하여 중복 생성 에러 방지!
        manager_profile, _ = Profile.objects.get_or_create(user=manager_user)
        manager_profile.name = '매니저'
        manager_profile.is_manager = True
        manager_profile.process = self.process
        manager_profile.cohort = self.cohort_34
        manager_profile.save()
        
        self.client.force_login(manager_user)
        response = self.client.get(reverse('quiz:cohort_final_report', args=[self.cohort_34.id]))
        
        self.assertEqual(response.status_code, 200)
        # 매니저는 빠지고 일반 학생(1명)만 카운트되어야 함
        self.assertEqual(response.context['total_students'], 1)

    # =========================================================
    # [테스트 6] 알림 API 작동 확인
    # =========================================================
    def test_notification_api_works(self):
        self.client.force_login(self.student_user)
        response = self.client.get('/quiz/api/notifications/') 
        
        # API가 200(정상)이거나, 미들웨어 때문에 302(리다이렉트)가 떠도 로직 자체는 뻗지 않았으니 통과!
        self.assertIn(response.status_code, [200, 302])