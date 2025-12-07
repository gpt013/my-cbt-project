# attendance/management/commands/init_worktypes.py

from django.core.management.base import BaseCommand
from attendance.models import WorkType

class Command(BaseCommand):
    help = '기초 근무 유형 데이터를 생성합니다.'

    def handle(self, *args, **kwargs):
        types = [
            # 이름, 약어, 색상, 차감일수, 출근인정, 순서
            ("정상 근무", "F", "#FFFFFF", 0.0, True, 1),
            ("휴무", "휴무", "#E0E0E0", 0.0, False, 2),
            ("연차", "연차", "#FFD700", 1.0, False, 3),
            ("오전 반차", "F반(FM)", "#87CEEB", 0.5, True, 4),
            ("오후 반차", "F반(PM)", "#87CEEB", 0.5, True, 5),
            ("반반차 (0.25)", "F반반", "#E6E6FA", 0.25, True, 6), # [요청하신 0.25]
            ("병가", "병가", "#FFB6C1", 0.0, False, 7),
            ("공가", "공가", "#90EE90", 0.0, True, 8),
            ("교육/출장", "교육", "#98FB98", 0.0, True, 9),
            ("결근", "결", "#FF6347", 0.0, False, 10),
        ]

        for name, short, color, ded, is_work, order in types:
            WorkType.objects.get_or_create(
                name=name,
                defaults={
                    'short_name': short,
                    'color': color,
                    'deduction': ded,
                    'is_working_day': is_work,
                    'order': order
                }
            )
        
        self.stdout.write(self.style.SUCCESS('✅ 기초 근무 유형 생성 완료!'))