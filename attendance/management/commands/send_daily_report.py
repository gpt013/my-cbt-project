from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.utils import timezone
from django.conf import settings
from attendance.models import DailySchedule
from accounts.models import PartLeader

class Command(BaseCommand):
    help = '매일 08:00, 담당 PL에게 소속 교육생의 금일 근태 현황을 메일로 발송합니다.'

    def handle(self, *args, **kwargs):
        today = timezone.now().date()
        print(f"📧 [근태 리포트] {today} 발송 시작...")
        
        # 1. 이메일이 등록된 모든 PL 가져오기
        pls = PartLeader.objects.filter(email__isnull=False)
        
        sent_count = 0
        
        for pl in pls:
            # 2. 해당 PL이 담당하는 교육생들의 '오늘 스케줄' 조회
            # (프로필의 pl 필드가 이 PartLeader인 사람들을 찾음)
            schedules = DailySchedule.objects.filter(
                profile__pl=pl, 
                date=today
            ).select_related('profile', 'work_type')
            
            # 담당 교육생이 없거나 스케줄이 없으면 건너뜀
            if not schedules.exists():
                continue
            
            # 3. 메일 본문 작성 (텍스트 형식)
            lines = []
            lines.append(f"📅 [{today.strftime('%Y-%m-%d')}] {pl.process.name if pl.process else ''} 근태 현황 보고")
            lines.append(f"수신: {pl.name} 파트장님\n")
            
            total = schedules.count()
            verified_cnt = 0
            late_cnt = 0
            issue_cnt = 0
            
            detail_lines = []
            
            for s in schedules:
                # 상태 판정
                state_text = "❓ 미인증"
                
                if s.is_mdm_verified:
                    state_text = "✅ 출석"
                    verified_cnt += 1
                    if s.is_late:
                        state_text = "⚠️ 지각"
                        late_cnt += 1
                else:
                    # 근무 유형이 '휴무', '연차' 등인 경우
                    if s.work_type and not s.work_type.is_working_day:
                        state_text = f"💤 {s.work_type.name}"
                    else:
                        # 근무일인데 인증 안 함
                        issue_cnt += 1
                
                # 한 줄 요약: [상태] 이름 (근무유형)
                detail_lines.append(f"{state_text} | {s.profile.name} ({s.work_type.name if s.work_type else '기본'})")

            # 요약 통계
            lines.append(f"■ 총원: {total}명")
            lines.append(f"■ 출석: {verified_cnt}명 (지각 {late_cnt}명)")
            lines.append(f"■ 미인증/이슈: {issue_cnt}명")
            lines.append("-" * 40)
            
            # 상세 명단 추가
            lines.extend(detail_lines)
            
            lines.append("-" * 40)
            lines.append("\n※ 본 메일은 시스템에서 08:00에 자동 발송되었습니다.")
            lines.append("※ 미인증 인원은 MDM 업로드를 독려해주세요.")

            email_subject = f"[근태알림] {today.strftime('%m/%d')} {pl.process.name if pl.process else ''} 출결 현황"
            email_body = "\n".join(lines)

            # 4. 실제 전송
            try:
                send_mail(
                    email_subject,
                    email_body,
                    settings.EMAIL_HOST_USER,
                    [pl.email],
                    fail_silently=False,
                )
                self.stdout.write(f" - {pl.name} ({pl.email}) 전송 완료")
                sent_count += 1
            except Exception as e:
                self.stdout.write(self.style.ERROR(f" - {pl.name} 전송 실패: {e}"))

        self.stdout.write(self.style.SUCCESS(f"✅ 총 {sent_count}건의 리포트 발송이 완료되었습니다."))