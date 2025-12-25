# attendance/management/commands/send_daily_report.py

from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.utils import timezone
from django.conf import settings
from accounts.models import Profile
from attendance.models import Attendance
import datetime

class Command(BaseCommand):
    help = '매일 아침 출근 현황(지각/미출근)을 관리자에게 메일로 전송합니다.'

    def handle(self, *args, **options):
        today = timezone.now().date()
        
        # 1. 기준 시간 설정 (예: 08:00 까지 출근해야 함)
        limit_hour = 8
        limit_minute = 0
        limit_time = datetime.time(limit_hour, limit_minute)

        # 2. 전체 교육생 명단 (재직중인 사람만)
        students = Profile.objects.filter(status='attending').exclude(is_manager=True).exclude(is_pl=True)
        
        # 3. 출근 기록 조회
        attendance_records = Attendance.objects.filter(date=today)
        attended_user_ids = attendance_records.values_list('user_id', flat=True)

        # 4. 분류 (지각 / 미출근 / 정상)
        late_list = []
        absent_list = []
        normal_list = []

        for student in students:
            # 출근 기록이 있는가?
            if student.user.id in attended_user_ids:
                record = attendance_records.get(user=student.user)
                # 지각 여부 체크 (UTC/KST 등 시간대 고려 필요, 여기선 단순 로직)
                # record.check_in_time은 datetime 객체
                check_in_local = timezone.localtime(record.check_in_time).time()
                
                if check_in_local > limit_time:
                    late_list.append(f"{student.name} ({check_in_local.strftime('%H:%M')} 출근)")
                else:
                    normal_list.append(f"{student.name}")
            else:
                # 기록 없음 -> 미출근
                absent_list.append(student.name)

        # 5. 메일 본문 작성
        subject = f"[PMTC] {today.strftime('%Y-%m-%d')} 교육생 출근 현황 리포트"
        message = f"""
        안녕하세요, 관리자님.
        {today.strftime('%Y-%m-%d')} 기준 출근 현황을 알려드립니다.
        (기준 시간: {limit_hour:02d}:{limit_minute:02d})

        🔴 미출근자 ({len(absent_list)}명):
        {', '.join(absent_list) if absent_list else '없음'}

        🟡 지각자 ({len(late_list)}명):
        {', '.join(late_list) if late_list else '없음'}

        🟢 정상 출근 ({len(normal_list)}명):
        {len(normal_list)}명 확인됨.

        * 본 메일은 시스템에 의해 자동 발송되었습니다.
        """

        # 6. 관리자 이메일 주소 가져오기 (settings.py의 ADMINS 또는 직접 지정)
        # 예시로 settings에 정의된 발신자 주소나 특정 관리자 주소 사용
        recipient_list = ['admin@example.com'] # [수정 필요] 실제 관리자 이메일로 변경!

        try:
            send_mail(
                subject,
                message,
                settings.EMAIL_HOST_USER, # 보내는 사람
                recipient_list,
                fail_silently=False,
            )
            self.stdout.write(self.style.SUCCESS(f'메일 발송 성공: {len(recipient_list)}명에게 전송함'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'메일 발송 실패: {str(e)}'))