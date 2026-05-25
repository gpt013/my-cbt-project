# quiz/views_facility.py

from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.utils.dateparse import parse_datetime
import datetime
from datetime import date, timedelta
from django.utils import timezone
from django.db.models import Count
from .models import Room, Reservation, Notification # 모델 임포트 필수!
from quiz.views import broadcast_realtime_notification
from django.contrib.auth.models import User
# accounts 앱의 모델 가져오기 (없으면 에러나니 꼭 확인)
try:
    from accounts.models import Profile, Process, Cohort,Company
except ImportError:
    # 혹시 모를 에러 방지용 더미 클래스
    Profile = None
    Process = None
    Cohort = None
    
from django.views.decorators.http import require_POST, require_GET 
from django.utils.dateparse import parse_datetime
# [헬퍼] 알림 발송
def send_notification(user, message, notification_type='facility', related_url=None):
    if user:
        Notification.objects.create(
            recipient=user, 
            message=message, 
            notification_type=notification_type,
            related_url=related_url # ★ 드디어 주소가 DB에 저장됩니다!
        )
        broadcast_realtime_notification(user.id)

# [헬퍼] 안전한 날짜 변환 (Timezone 에러 방지)
def safe_parse_datetime(date_str):
    if not date_str: return None
    dt = parse_datetime(date_str)
    if dt and timezone.is_naive(dt):
        return timezone.make_aware(dt)
    return dt

# [1] 대시보드
@login_required
def facility_dashboard(request):
    if not request.user.is_staff:
        return redirect('quiz:index')
    
    rooms = Room.objects.filter(is_active=True)
    companies = Company.objects.all()  # ★ 이 줄을 반드시 추가해야 합니다!
    today = timezone.localtime(timezone.now())
    
    # 1. 이번 달 통계 데이터
    start_month = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_res = Reservation.objects.filter(start_time__gte=start_month)
    
    total_confirmed = month_res.filter(status='confirmed').count()
    total_pending = month_res.filter(status='pending').count()
    total_rejected = month_res.filter(status='rejected').count()
    
    company_stats = month_res.filter(status='confirmed').values('company_name').annotate(count=Count('id')).order_by('-count')
    process_stats = month_res.filter(status='confirmed').values('process_name').annotate(count=Count('id')).order_by('-count')
    
    # 2. ★ [수정됨] "오늘의 예약" 리스트 (강의실별 그룹화)
    today_start = today.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    # (1) 데이터 가져오기: 반드시 '강의실 이름' 순으로 정렬해야 그룹화가 가능합니다.
    raw_reservations = Reservation.objects.filter(
        start_time__lte=today_end,
        end_time__gte=today_start
    ).exclude(status='rejected').select_related('room', 'user__profile').order_by('room__name', 'start_time')

    # (2) 파이썬 로직으로 그룹화: [{'room': RoomObj, 'events': [Res1, Res2]}, ...] 형태
    today_reservations = []
    if raw_reservations:
        current_room = None
        current_group = None
        
        for res in raw_reservations:
            # 방이 바뀌면 새로운 그룹 시작
            if res.room != current_room:
                current_room = res.room
                current_group = {
                    'room': current_room, 
                    'events': []
                }
                today_reservations.append(current_group)
            
            # 현재 그룹에 예약 추가
            current_group['events'].append(res)

    # 3. 내 알림
    my_notifications = Notification.objects.filter(
        recipient=request.user, 
        is_read=False, 
        notification_type='facility'  # <--- 이 부분이 추가되었습니다.
    ).order_by('-created_at')

    my_reservations = Reservation.objects.filter(user=request.user).order_by('-start_time')[:10]

    is_manager = request.user.is_superuser or request.user.groups.filter(name='FacilityManager').exists()

    context = {
        'rooms': rooms,
        'company_stats': company_stats,
        'process_stats': process_stats,
        'today_reservations': today_reservations, 
        'is_manager': is_manager,
        'notifications': my_notifications,
        'companies': companies,
        'my_reservations': my_reservations,
        'total_confirmed': total_confirmed,
        'total_pending': total_pending,
        'total_rejected': total_rejected,
    }
    return render(request, 'quiz/manager/facility_dashboard.html', context)

@login_required
def facility_events(request):
    action = request.GET.get('action')
    if action == 'monthly_stats':
        date_str = request.GET.get('date')
        try:
            view_date = parse_datetime(date_str + "T00:00:00")
            if timezone.is_naive(view_date): view_date = timezone.make_aware(view_date)
        except:
            view_date = timezone.localtime(timezone.now())

        start_month = view_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        import calendar
        last_day = calendar.monthrange(start_month.year, start_month.month)[1]
        end_month = start_month.replace(day=last_day, hour=23, minute=59, second=59, microsecond=999999)

        # ★ 해당 월에 '걸쳐있는' 모든 내 예약 가져오기
        my_res_qs = Reservation.objects.filter(
            user=request.user, start_time__lte=end_month, end_time__gte=start_month
        ).order_by('start_time')

        def get_my_list(status):
            return [{
                'title': r.title, 'room_name': r.room.name, 
                'company': r.company_name or '소속 미상',
                # ★ [수정] 다중일이면 시작~종료 날짜 모두 표시, 당일이면 시간만 표시
                'start': f"{timezone.localtime(r.start_time).strftime('%m/%d %H:%M')} ~ {timezone.localtime(r.end_time).strftime('%m/%d %H:%M')}" if timezone.localtime(r.start_time).date() != timezone.localtime(r.end_time).date() else f"{timezone.localtime(r.start_time).strftime('%m/%d %H:%M')} ~ {timezone.localtime(r.end_time).strftime('%H:%M')}",
                'user_name': r.user.profile.name if hasattr(r.user, 'profile') else r.user.username
            } for r in my_res_qs.filter(status=status).order_by('start_time')]

        my_stats = {
            'confirmed': get_my_list('confirmed'),
            'pending': get_my_list('pending'),
            'rejected': get_my_list('rejected'),
        }
    

        # 2. 내 예약 리스트 (다중일 표기 로직 추가)
        my_res_data = []
        for r in my_res_qs[:10]: # 목록은 최근 10개만
            s_dt = timezone.localtime(r.start_time)
            e_dt = timezone.localtime(r.end_time)
            
            # 당일 예약이면 시간만, 다중일이면 날짜~날짜 표기!
            if s_dt.date() == e_dt.date():
                time_str = f"{s_dt.strftime('%m/%d')} {s_dt.strftime('%H:%M')} ~ {e_dt.strftime('%H:%M')}"
            else:
                time_str = f"{s_dt.strftime('%m/%d %H:%M')} ~ {e_dt.strftime('%m/%d %H:%M')}"

            my_res_data.append({
                'title': r.title, 'status': r.status, 'room_name': r.room.name,
                'time_str': time_str
            })

        # 3. 관리자 통계 (해당 월 기준)
        is_manager = request.user.is_superuser or request.user.groups.filter(name='FacilityManager').exists()
        stats_data = {}
        if is_manager:
            all_res = Reservation.objects.filter(start_time__lte=end_month, end_time__gte=start_month)
            
            def get_list(status):
                return [{
                    'title': r.title, 'room_name': r.room.name, 
                    'company': r.company_name or '소속 미상',
                    # ★ [수정] 다중일이면 시작~종료 날짜 모두 표시, 당일이면 시간만 표시
                    'start': f"{timezone.localtime(r.start_time).strftime('%m/%d %H:%M')} ~ {timezone.localtime(r.end_time).strftime('%m/%d %H:%M')}" if timezone.localtime(r.start_time).date() != timezone.localtime(r.end_time).date() else f"{timezone.localtime(r.start_time).strftime('%m/%d %H:%M')} ~ {timezone.localtime(r.end_time).strftime('%H:%M')}",
                    'user_name': r.user.profile.name if hasattr(r.user, 'profile') else r.user.username
                } for r in all_res.filter(status=status).order_by('start_time')]

            stats_data = {
                'confirmed': get_list('confirmed'),
                'pending': get_list('pending'),
                'rejected': get_list('rejected'),
            }
            companies = all_res.filter(status='confirmed').values('company_name').annotate(count=Count('id')).order_by('-count')
            stats_data['companies'] = [{'name': c['company_name'] or '소속 미상', 'count': c['count']} for c in companies]

        return JsonResponse({
            'is_manager': is_manager,
            'my_stats': my_stats,        # ★ 내 통계 추가
            'my_reservations': my_res_data,
            'stats': stats_data,
            'month_str': f"{start_month.year}년 {start_month.month}월"
        })
    
    # 1. 파라미터 가져오기
    start = safe_parse_datetime(request.GET.get('start'))
    end = safe_parse_datetime(request.GET.get('end'))
    room_id = request.GET.get('room_id')

    events = []
    if start and end:
        # 2. 날짜 범위 필터링 (월이 넘어가는 다중일 일정도 잡히도록 교집합 조건으로 변경!)
        query = Reservation.objects.filter(start_time__lt=end, end_time__gt=start)
        
        # 3. 특정 강의실 필터링 (All이 아닐 경우)
        if room_id and room_id != 'all':
             query = query.filter(room_id=room_id)
        
        # 쿼리 최적화 (매니저 정보 미리 가져오기)
        events = query.select_related('room', 'user__profile').prefetch_related('room__managers')
    
    data = []
    for e in events:
        # 색상 로직
        if e.status == 'pending': color = '#adb5bd'   # 대기 (회색)
        elif e.status == 'rejected': color = '#dc3545' # 반려 (빨강)
        else: color = e.room.color                    # 확정 (방 고유색)
        
        # 이름/소속 표시 로직
        try:
            profile = e.user.profile
            user_name = profile.name
            company = e.company_name or (profile.company.name if profile.company else "")
            process = e.process_name or (profile.process.name if profile.process else "")
            prefix = f"[{company}/{process}] {user_name}"
        except:
            user_name = e.user.username
            prefix = f"[{user_name}]"

        # ★★★ [권한 로직 강화] ★★★
        is_superuser = request.user.is_superuser
        is_designated_manager = request.user in e.room.managers.all()
        is_owner = (e.user == request.user)
        
        can_approve = (is_superuser or is_designated_manager)
        can_edit = (can_approve or is_owner)

        data.append({
            'id': e.id,
            'room_id': e.room.id,
            'title': f"{prefix} - {e.title}",
            'start': e.start_time.isoformat(),
            'end': e.end_time.isoformat(),
            'color': color,
            'editable': can_edit, 
            'extendedProps': {
                'status_code': e.status, 
                'status_label': e.get_status_display(),
                'company': e.company_name, 
                'process': e.process_name,
                'username': user_name,
                'attendees': e.attendees,   # ★ 이 줄 추가
                'full_desc': e.title,
                'is_admin': can_approve,
                'can_approve': can_approve,
                'can_manage': can_edit,
                'can_edit': can_edit
            }
        })
        
    # =========================================================
    # ★ [추가] PMTC 기수(교육기간) 전체 일정 표시 (캘린더 맨 위 띠)
    # =========================================================
    if Cohort and start and end:
        # 달력 현재 화면(시작~끝 날짜)과 겹치는 기수 찾기
        overlapping_cohorts = Cohort.objects.filter(
            start_date__lte=end.date(),
            end_date__gte=start.date()
        )
        
        for c in overlapping_cohorts:
            current_start = c.start_date
            week_num = 1
            
            while current_start <= c.end_date:
                # ★ [핵심] 무조건 7일이 아니라 '토요일'을 기준으로 자릅니다!
                # 파이썬 weekday(): 월=0, 화=1, 수=2, 목=3, 금=4, 토=5, 일=6
                # 현재 날짜에서 이번 주 토요일까지 남은 일수 계산
                days_to_saturday = (5 - current_start.weekday()) % 7
                current_end = current_start + timedelta(days=days_to_saturday)
                
                # 기수 종료일을 넘지 않도록 방어
                if current_end > c.end_date:
                    current_end = c.end_date
                
                # 현재 달력 화면에 보이는 날짜인지 확인
                if current_start <= end.date() and current_end >= start.date():
                    # FullCalendar 종일(allDay) 이벤트는 종료일에 하루를 더해줘야 예쁘게 꽉 찹니다.
                    fc_end_date = current_end + timedelta(days=1)
                    
                    data.append({
                        'id': f'cohort_{c.id}_w{week_num}',
                        'title': f'🏫[ PMTC {c.name} 교육기간 {week_num}W ] ',
                        'start': current_start.isoformat(),
                        'end': fc_end_date.isoformat(),
                        'color': '#ffecb5',      # 부드러운 노란색 배경
                        'textColor': '#664d03',  # 진한 갈색 텍스트
                        'allDay': True,          # 달력 맨 위에 '종일' 띠로 고정
                        'editable': False,       # 마우스로 드래그 금지
                        'extendedProps': {
                            'is_cohort': True
                        }
                    })
                
                # 다음 주차 시작일 (다음 주 일요일)
                current_start = current_end + timedelta(days=1)
                week_num += 1

    return JsonResponse(data, safe=False)

# [3] 예약 신청 (알림 로직 수정: 지정 관리자에게 알림 발송)
@login_required
def facility_reserve(request):
    if request.method == 'POST':
        try:
            # 1. 수정인지 생성인지 확인
            event_id = request.POST.get('id')
            
            # 2. 다중 선택된 강의실 ID 리스트 가져오기 (room_ids)
            room_ids = request.POST.getlist('room_ids') 
            if not room_ids:
                return JsonResponse({'status': 'error', 'message': '강의실을 선택해주세요.'})

            start_dt = safe_parse_datetime(request.POST.get('start_time'))
            end_dt = safe_parse_datetime(request.POST.get('end_time'))
            title = request.POST.get('title')
            attendees = request.POST.get('attendees', 0)
            company_name = request.POST.get('company_name', '')

            if not start_dt or not end_dt: 
                return JsonResponse({'status': 'error', 'message': '날짜 오류'})
            if start_dt >= end_dt: 
                return JsonResponse({'status': 'error', 'message': '종료 시간이 시작 시간보다 빠를 수 없습니다.'})

            # 3. 예약 처리 (루프 돌면서 선택한 방 개수만큼 예약 생성)
            # 수정 모드일 때는 선택된 첫 번째 방 하나만 처리하는 것이 안전합니다.
            if event_id:
                res = get_object_or_404(Reservation, pk=event_id)
                room = get_object_or_404(Room, pk=room_ids[0]) # 수정 시엔 첫 번째 선택된 방으로
                
                # 권한 체크
                is_approver = request.user.is_superuser or (request.user in room.managers.all())
                if not (is_approver or res.user == request.user):
                    return JsonResponse({'status': 'error', 'message': '수정 권한이 없습니다.'})
                
                res.room = room
                res.title = title
                res.start_time = start_dt
                res.end_time = end_dt
                res.attendees = attendees
                res.company_name = company_name
                if not is_approver: res.status = 'pending'
                
                # 중복 체크 후 저장
                if res.check_overlap():
                    return JsonResponse({'status': 'error', 'message': f'[{room.name}] 해당 시간에 이미 예약이 있습니다.'})
                res.save()
            
            else:
                # [신규 생성 모드] 선택한 모든 강의실에 대해 각각 예약 생성
                for r_id in room_ids:
                    room = get_object_or_404(Room, pk=r_id)
                    is_approver = request.user.is_superuser or (request.user in room.managers.all())
                    
                    new_res = Reservation(
                        room=room, 
                        user=request.user, 
                        title=title,
                        start_time=start_dt, 
                        end_time=end_dt,
                        attendees=attendees,
                        company_name=company_name,
                        status='confirmed' if is_approver else 'pending'
                    )
                    
                    # 중복 체크
                    if new_res.check_overlap():
                        return JsonResponse({'status': 'error', 'message': f'[{room.name}] 이미 예약된 시간입니다.'})
                    new_res.save()

                    # 관리자 알림 발송 (생략 가능)
                    if not is_approver:
                        msg = f"📢 [예약신청] {request.user.profile.name if hasattr(request.user, 'profile') else request.user.username}님이 {room.name} 예약을 신청했습니다."
                        
                        target_users = set() # 중복 수신 방지 바구니
                        
                        # 1. 해당 강의실의 우선 배정 공정(target_process) 매니저들 싹 다 담기
                        if room.target_process:
                            for p in Profile.objects.filter(process=room.target_process, is_manager=True):
                                target_users.add(p.user)
                                
                        # 2. 지정 관리자들 담기
                        for m in room.managers.all():
                            target_users.add(m)
                            
                        # 3. 바구니에 담긴 모두에게 알림 발송!
                        for user_to_notify in target_users:
                            send_notification(user_to_notify, msg)

            return JsonResponse({'status': 'success', 'message': '예약이 정상적으로 처리되었습니다.'})

        except Exception as e:
            return JsonResponse({'status': 'error', 'message': f'서버 오류: {str(e)}'})
            
    return JsonResponse({'status': 'error', 'message': '잘못된 요청입니다.'})

# [4] 예약 변경 (권한 체크)
@login_required
def facility_update(request):
    if request.method == 'POST':
        try:
            event = get_object_or_404(Reservation, pk=request.POST.get('id'))
            
            # 권한: 슈퍼유저 OR 지정 관리자 OR 본인
            is_admin = request.user.is_superuser or (request.user in event.room.managers.all())
            if not (is_admin or event.user == request.user): 
                return JsonResponse({'status': 'error', 'message': '권한 없음'})
            
            start_dt = safe_parse_datetime(request.POST.get('start'))
            end_dt = safe_parse_datetime(request.POST.get('end'))
            
            event.start_time, event.end_time = start_dt, end_dt
            if event.check_overlap(): 
                return JsonResponse({'status': 'error', 'message': '중복된 시간입니다.'})
            
            # 일반인은 수정 시 승인 대기로 전환
            if not is_admin:
                reason = request.POST.get('reason', '사유 미기재')
                event.status = 'pending'
                msg = '시간이 변경되었습니다. (관리자 재승인 필요)'
                
                # ★ 알림 발송: 지정 관리자 + 공정 매니저
                target_users = set()
                if event.room.target_process:
                    for p in Profile.objects.filter(process=event.room.target_process, is_manager=True):
                        target_users.add(p.user)
                for m in event.room.managers.all():
                    target_users.add(m)
                    
                for user_to_notify in target_users:
                    send_notification(user_to_notify, f"✏️ [수정 요청] {event.title} 시간 변경\n사유: {reason}")
            else:
                msg = '시간 변경 완료'

            event.save()
            return JsonResponse({'status': 'success', 'message': msg})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})
    return JsonResponse({'status': 'error'})

# [5] 예약 관리 (승인/반려) - 지정 관리자도 가능하게
@login_required
def facility_action(request, event_id):
    event = get_object_or_404(Reservation, pk=event_id)
    
    # ★ [핵심] 슈퍼유저 이거나 이 방의 지정 관리자여야 함
    is_admin = request.user.is_superuser or (request.user in event.room.managers.all())
    action = request.POST.get('action')

    if action in ['approve', 'reject'] and not is_admin: 
        return JsonResponse({'status': 'error', 'message': '관리 권한이 없습니다.'})
    
    if action == 'delete' and not (is_admin or event.user == request.user): 
        return JsonResponse({'status': 'error', 'message': '권한 없음'})

    if action == 'approve':
        if event.check_overlap(): return JsonResponse({'status': 'error', 'message': '승인 실패(이미 확정된 예약 존재)'})
        
        # ★ 중복된 대기열(pending) 찾아서 자동 반려 처리!
        reject_reason = request.POST.get('reject_reason', f"중복 중 선택한 일정({event.title})으로 인한 변경")
        overlapping_pending = Reservation.objects.filter(
            room=event.room, status='pending',
            start_time__lt=event.end_time, end_time__gt=event.start_time
        ).exclude(pk=event.pk)
        
        from django.urls import reverse # 상단에 없으면 에러나니 여기서 안전하게 임포트
        facility_url = reverse('quiz:facility_dashboard') # 대시보드 주소

        for p_res in overlapping_pending:
            p_res.status = 'rejected'
            p_res.save()
            # ★ related_url 추가
            send_notification(p_res.user, f"❌ 중복 예약이 반려되었습니다: {p_res.title}\n사유: {reject_reason}", notification_type='facility', related_url=facility_url)

        event.status = 'confirmed'
        event.save()
        # ★ related_url 추가
        send_notification(event.user, f"✅ 예약이 승인되었습니다: {event.title}", notification_type='facility', related_url=facility_url)
        
        # ★ [알림 발송] 확정 소식도 양쪽 모두 공유
        target_users = set()
        if event.room.target_process:
            for p in Profile.objects.filter(process=event.room.target_process, is_manager=True):
                target_users.add(p.user)
        for m in event.room.managers.all():
            target_users.add(m)
            
        for user_to_notify in target_users:
            if user_to_notify != request.user:
                # ★ related_url 추가
                send_notification(user_to_notify, f"🆗 [확정] {event.title} 예약이 승인처리 되었습니다.", notification_type='facility', related_url=facility_url)

    elif action == 'reject':
        reject_reason = request.POST.get('reject_reason', '사유 없음')
        event.status = 'rejected'
        event.save()
        from django.urls import reverse
        # ★ related_url 추가
        send_notification(event.user, f"❌ 예약이 반려되었습니다: {event.title}\n사유: {reject_reason}", notification_type='facility', related_url=reverse('quiz:facility_dashboard'))

    elif action == 'delete':
        event.delete()
        if event.user != request.user: 
            send_notification(event.user, f"🗑 예약이 취소되었습니다: {event.title}")
        
    return JsonResponse({'status': 'success', 'message': '처리 완료'})

# =========================================================
# ★ [추가] 알림 관련 기능 (삭제, 전체삭제, API)
# =========================================================

@login_required
def notification_read(request, noti_id):
    """단일 알림 읽음 처리 (가짜 알림 무시 조항 유지)"""
    if int(noti_id) == 0: 
        return JsonResponse({'status': 'success'}) 
    noti = get_object_or_404(Notification, id=noti_id, recipient=request.user)
    noti.is_read = True
    noti.save()
    return JsonResponse({'status': 'success'})

@login_required
def notification_delete(request, noti_id):
    """단일 알림 영구 삭제"""
    if int(noti_id) == 0: 
        return JsonResponse({'status': 'success'}) 
    noti = get_object_or_404(Notification, id=noti_id, recipient=request.user)
    noti.delete()
    return JsonResponse({'status': 'success'})

@login_required
def notification_clear_all(request):
    """알림 전체 삭제 (SweetAlert2 연동용)"""
    Notification.objects.filter(recipient=request.user).delete()
    return JsonResponse({'status': 'success'})

# ──────────────────────────────────────────────────────────
# 🎯 [핵심 추가] 상단 벨 아이콘 드롭다운 오픈 시 호출되는 일괄 읽음 처리 마스터 API
# ──────────────────────────────────────────────────────────
@login_required
@require_POST
def api_mark_all_notifications_as_read(request):
    """
    사용자가 상단 네비게이션 바의 알림 드롭다운을 연 순간 작동하여
    해당 유저에게 도착한 모든 '미열람 알림(is_read=False)'을 즉시 '읽음'으로 일괄 전환합니다.
    화면의 '빨간 배지 숫자'가 계속 남아있는 UX 오류를 뿌리뽑는 핵심 기지입니다.
    """
    unread_notis = Notification.objects.filter(recipient=request.user, is_read=False)
    if unread_notis.exists():
        # update() 쿼리로 한 번에 밀어버려 DB 오버헤드를 제로로 만듭니다.
        updated_count = unread_notis.update(is_read=True)
        return JsonResponse({'status': 'success', 'message': f'{updated_count}건의 알림이 정상 확인되었습니다.'})
    return JsonResponse({'status': 'success', 'message': '확인할 새로운 알림이 없습니다.'})


@login_required
def notification_api_list(request):
    """상단 벨 아이콘용 알림 목록 실시간 반환 API (+ 5일 지난 알림 청소 & 중복 방지 락 탑재)"""
    
    # 1. 5일이 지난 일반 알림 자동 청소
    expiration_date = timezone.now() - timedelta(days=5)
    Notification.objects.filter(recipient=request.user, created_at__lt=expiration_date).delete()

    # =========================================================
    # 🛡️ [2중 방어선] 평가 대기 인원 '독촉 알림' 중복 생성 스패밍 처단 로직
    # =========================================================
    if request.user.is_staff:
        today = timezone.now().date()
        
        # 평가 대기 대상 프로필 조회
        pending_profiles = Profile.objects.filter(
            cohort__end_date__lt=today,
            status__in=['attending', 'caution', 'counseling']
        ).exclude(user__is_superuser=True).exclude(is_manager=True).select_related('cohort', 'process')

        if not request.user.is_superuser:
            if hasattr(request.user, 'profile') and request.user.profile.process:
                pending_profiles = pending_profiles.filter(process=request.user.profile.process)
            else:
                pending_profiles = pending_profiles.none()

        from django.urls import reverse

        for p in pending_profiles:
            cohort_name = p.cohort.name if p.cohort else "미지정"
            process_name = p.process.name if p.process else "미지정"
            days_passed = (today - p.cohort.end_date).days
            target_url = reverse('quiz:evaluate_trainee', args=[p.id])

            # 알림 메시지 정의
            if days_passed <= 1:
                msg = f"[{cohort_name}/{process_name}] {p.name}님 기수가 종료되었습니다. 상세 페이지에서 최종 평가 및 수료 처리를 진행해주세요."
            else:
                msg = f"🚨 [D+{days_passed}일 지연] [{cohort_name}/{process_name}] {p.name}님 수료 처리가 안되었습니다! 즉시 작성 부탁드립니다."

            # 🛡️ 핵심 방어: 이미 동일 타겟팅 주소로 전송된 알림이 있는지 우선 검색
            existing_noti = Notification.objects.filter(
                recipient=request.user,
                notification_type='pending_eval',
                related_url=target_url
            ).first()

            if not existing_noti:
                # 아예 처음 생성되는 알림일 때만 신규 생성
                Notification.objects.create(
                    recipient=request.user,
                    message=msg,
                    related_url=target_url,
                    notification_type='pending_eval',
                    is_read=False # 새로 왔으니 알림 켜기
                )
            else:
                # 🛡️ 버그 킬러: 이미 알림이 존재한다면 절대 중복 생성하지 않고, 날짜가 바뀌었을 때만 내용 '갱신(Update)'만 수행!
                if existing_noti.created_at.date() < today:
                    existing_noti.message = msg
                    existing_noti.is_read = False  # 새 날짜가 되었으니 다시 빨간 불 켜기
                    existing_noti.created_at = timezone.now()  # 리스트 맨 위로 상향 조정
                    existing_noti.save()

    # =========================================================
    # ★ [추가] 시설/장비 예약 당일 아침 브리핑 (Daily Reminder)
    # =========================================================
    if request.user.is_superuser or request.user.groups.filter(name='FacilityManager').exists() or hasattr(request.user, 'profile'):
        today = timezone.localtime().date()
        today_start = timezone.make_aware(timezone.datetime.combine(today, timezone.datetime.min.time()))
        today_end = timezone.make_aware(timezone.datetime.combine(today, timezone.datetime.max.time()))

        already_sent_today = Notification.objects.filter(
            recipient=request.user,
            notification_type='facility_daily',
            created_at__gte=today_start
        ).exists()

        if not already_sent_today:
            today_res = Reservation.objects.filter(
                status='confirmed',
                start_time__lte=today_end,
                end_time__gte=today_start
            ).select_related('room', 'user__profile')

            from collections import defaultdict
            room_map = defaultdict(list)
            
            for res in today_res:
                is_my_room = False
                if request.user.is_superuser:
                    is_my_room = True
                elif res.room.target_process and hasattr(request.user, 'profile') and request.user.profile.process == res.room.target_process and request.user.profile.is_manager:
                    is_my_room = True
                elif request.user in res.room.managers.all():
                    is_my_room = True

                if is_my_room:
                    room_map[res.room.name].append(res)

            from django.urls import reverse
            facility_url = reverse('quiz:facility_dashboard')

            for room_name, res_list in room_map.items():
                res_list.sort(key=lambda x: x.start_time)
                msg_lines = [f"🔔 [오늘의 일정] {room_name}에 금일 확정된 예약이 {len(res_list)}건 있습니다."]
                
                for r in res_list:
                    s_dt = timezone.localtime(r.start_time)
                    e_dt = timezone.localtime(r.end_time)
                    user_name = r.user.profile.name if hasattr(r.user, 'profile') else r.user.username
                    
                    if s_dt.date() < today < e_dt.date():
                        time_str = "종일 (연속 예약)"
                    elif s_dt.date() == today < e_dt.date():
                        time_str = f"{s_dt.strftime('%H:%M')} ~ (내일로 이어짐)"
                    elif s_dt.date() < today == e_dt.date():
                        time_str = f"(이전부터) ~ {e_dt.strftime('%H:%M')}"
                    else:
                        time_str = f"{s_dt.strftime('%H:%M')} ~ {e_dt.strftime('%H:%M')}"

                    msg_lines.append(f" - {time_str} : {r.title} ({user_name})")

                final_msg = "\n".join(msg_lines)

                Notification.objects.create(
                    recipient=request.user,
                    message=final_msg,
                    notification_type='facility_daily',
                    related_url=facility_url,
                    is_read=False
                )

    # =========================================================
    # 2.종국에 안 읽은 진짜 활성 알림 세트만 화면에 응답 전송
    # =========================================================
    notis = Notification.objects.filter(recipient=request.user, is_read=False).order_by('-created_at')
    count = notis.count()
    
    data = []
    for n in notis:
        icon = 'bi-info-circle text-primary' 
        
        if '근무변경' in n.message or '근무 변경' in n.message:
            icon = 'bi-calendar-date-fill text-success' 
        elif n.notification_type == 'facility': icon = 'bi-building text-success'
        elif n.notification_type == 'facility_daily': icon = 'bi-calendar-check-fill text-primary'
        elif n.notification_type == 'signup': icon = 'bi-person-plus-fill text-info'
        elif n.notification_type == 'exam': icon = 'bi-pencil-square text-warning'
        elif n.notification_type == 'pending_eval': icon = 'bi-exclamation-square-fill text-danger'
        elif n.notification_type == 'counseling': icon = 'bi-chat-left-dots-fill text-danger' 
        elif n.notification_type == 'chat_mention': icon = 'bi-chat-dots-fill text-primary' 
        elif n.notification_type == 'general': icon = 'bi-bell-fill text-secondary'

        data.append({
            'id': n.id,
            'message': n.message,
            'link': n.related_url if n.related_url else '#',
            'icon': icon,
            'time': n.created_at.strftime('%m/%d %H:%M')
        })
        
    return JsonResponse({'count': count, 'notifications': data})


def read_notification(request, id):
    # 1. 데이터베이스에서 해당 id의 알림 객체를 가져옵니다.
    notification = get_object_or_404(Notification, id=id)
    
    # 2. 읽음 처리를 합니다. (모델의 필드명에 맞게 수정하세요)
    notification.is_read = True 
    notification.save()
    
    # 3. 프론트엔드의 .then(res => res.json())이 잘 작동하도록 JSON 객체를 반환합니다.
    return JsonResponse({"status": "success", "message": "알림 읽음 처리 완료"})
        

import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from django.http import HttpResponse
from django.utils import timezone
from django.contrib.auth.decorators import login_required
import urllib.parse
from datetime import datetime, date, timedelta
import calendar
from .models import Reservation
 
 
# ──────────────────────────────────────────────────────────
# [1] 공휴일 데이터
# ──────────────────────────────────────────────────────────
def get_holiday_name(check_date):
    md = check_date.strftime('%m-%d')
    y = check_date.year
    
    fixed = {'01-01':'신정', '03-01':'삼일절', '05-05':'어린이날', '06-06':'현충일', '08-15':'광복절', '10-03':'개천절', '10-09':'한글날', '12-25':'성탄절'}
    if md in fixed: return fixed[md]
    
    var_holidays = {
        2024: {'02-09':'설연휴', '02-10':'설날', '02-11':'설연휴', '02-12':'대체휴일', '04-10':'선거일', '05-06':'대체휴일', '05-15':'부처님오신날', '09-16':'추석연휴', '09-17':'추석', '09-18':'추석연휴'},
        2025: {'01-28':'설연휴', '01-29':'설날', '01-30':'설연휴', '03-03':'대체휴일', '05-05':'부처님오신날', '05-06':'대체휴일', '10-05':'추석연휴', '10-06':'추석', '10-07':'추석연휴', '10-08':'대체휴일'},
        2026: {'02-16':'설연휴', '02-17':'설날', '02-18':'설연휴', '03-02':'대체휴일', '05-24':'부처님오신날', '05-25':'대체휴일', '06-03':'지방선거', '08-16':'대체휴일', '09-24':'추석연휴', '09-25':'추석', '09-26':'추석연휴', '10-05':'대체휴일'},
    }
    
    generic_var_list = {
        2027: ['02-06','02-07','02-08','02-09','03-03','05-13','08-16','09-14','09-15','09-16'],
        2028: ['01-26','01-27','01-28','05-02','10-02','10-03','10-04','10-05'],
        2029: ['02-12','02-13','02-14','05-07','05-20','09-21','09-22','09-23','09-24'],
        2030: ['02-02','02-03','02-04','02-05','05-06','05-09','06-12','09-11','09-12','09-13'],
        2031: ['01-22','01-23','01-24','05-28','09-30','10-01','10-02'],
        2032: ['02-10','02-11','02-12','03-03','05-14','09-18','09-19','09-20'],
        2033: ['01-30','01-31','02-01','05-06','10-07','10-08','10-09'],
        2034: ['02-18','02-19','02-20','05-25','09-26','09-27','09-28'],
        2035: ['02-07','02-08','02-09','05-15','09-15','09-16','09-17'],
    }
    
    if y in var_holidays and md in var_holidays[y]: return var_holidays[y][md]
    if y in generic_var_list and md in generic_var_list[y]:
        m = int(md.split('-')[0])
        if m in [1, 2]: return "설연휴"
        if m in [4, 5, 6]: return "부처님오신날/대체휴일"
        if m in [9, 10]: return "추석연휴"
        return "공휴일"
        
    return None
 
 
# ──────────────────────────────────────────────────────────
# [2] 스타일 헬퍼
# ──────────────────────────────────────────────────────────
def _fill(hex_color):
    return PatternFill('solid', fgColor=hex_color)
 
def _thin_border():
    s = Side(style='thin', color='AAAAAA')
    return Border(left=s, right=s, top=s, bottom=s)
 
def _thick_bottom_border():
    m = Side(style='medium', color='4472C4')
    t = Side(style='thin',   color='AAAAAA')
    return Border(left=t, right=t, top=t, bottom=m)
 
def _center(wrap=False):
    return Alignment(horizontal='center', vertical='center', wrap_text=wrap)
 
def _top_left():
    return Alignment(horizontal='left', vertical='top', wrap_text=True)
 
def _get_day_type(d):
    # ★ is_holiday 대신 get_holiday_name을 사용하도록 여기도 변경!
    if d.weekday() == 6 or get_holiday_name(d): return 'holiday'  # 일요일 or 공휴일
    if d.weekday() == 5: return 'sat'
    return 'weekday'
 
 
# ──────────────────────────────────────────────────────────
# [3] 목록형 시트 빌더
#     열 구성: 일자 | 요일 | PMTC/기수 일정 | 강의실별 예약 현황
# ──────────────────────────────────────────────────────────
def _build_list_sheet(wb, year, month, start_date, end_date, reservations, cohort_list):
    ws = wb.create_sheet(title=f"{year}년 {month}월_목록")
 
    # 컬럼 너비 (조금 더 여유있게 조정)
    ws.column_dimensions['A'].width = 14
    ws.column_dimensions['B'].width = 16
    ws.column_dimensions['C'].width = 40
    ws.column_dimensions['D'].width = 55
 
    # [색상 팔레트 정의 - 컨설팅 테마]
    COLOR_TITLE_BG = '1F3864'    # 짙은 네이비 (제목)
    COLOR_HEADER_BG = 'D9E1F2'   # 아주 연한 블루 (헤더)
    COLOR_COHORT_BG = 'FFF2CC'   # 연한 크림 (PMTC)
    COLOR_RES_BG = 'E7EFF6'      # 연한 하늘색 (예약)
    COLOR_HOLIDAY_BG = 'FCE4D6'  # 연한 핑크 (공휴일)
    COLOR_SAT_BG = 'E9F0F5'      # 연한 회색 (토요일)
 
    # ── 1행: 제목 ────────────────────────────────
    ws.merge_cells('A1:D1')
    t = ws['A1']
    t.value     = f"{year}년 {month}월 교육장 운영 일정표"
    t.font      = Font(name='맑은 고딕', size=14, bold=True, color='FFFFFF')
    t.fill      = _fill(COLOR_TITLE_BG)
    t.alignment = _center()
    ws.row_dimensions[1].height = 35
 
    # ── 2행: 헤더 ────────────────────────────────
    headers = ["일자", "요일/공휴일", "기수 교육 일정 (PMTC)", "강의실별 상세 예약 현황"]
    for ci, h in enumerate(headers, 1):
        cell = ws.cell(row=2, column=ci, value=h)
        cell.font      = Font(name='맑은 고딕', size=10, bold=True, color='203764')
        cell.fill      = _fill(COLOR_HEADER_BG)
        cell.alignment = _center()
        cell.border    = _thin_border()
    ws.row_dimensions[2].height = 25
 
    # ── 데이터 맵 구축 (주차 계산 로직 포함) ────────────────
    cohort_map = {}
    for c in cohort_list:
        d = c.start_date
        while d <= c.end_date:
            # 주차 계산: (현재날짜 - 시작날짜).days // 7 + 1
            week_num = (d - c.start_date).days // 7 + 1
            cohort_map.setdefault(d, []).append(f"🏫 PMTC ({c.name}기) 교육기간 ({week_num}W)")
            d += timedelta(days=1)
 
    res_map = {}
    for r in reservations:
        s_l = timezone.localtime(r.start_time)
        e_l = timezone.localtime(r.end_time)
        s_d, e_d = s_l.date(), e_l.date()
        cur = s_d
        while cur <= e_d:
            room_name = r.room.name if r.room else "미지정"
            if cur == s_d == e_d:   t_str = f"{s_l.strftime('%H:%M')}~{e_l.strftime('%H:%M')}"
            elif cur == s_d:        t_str = f"{s_l.strftime('%H:%M')}~"
            elif cur == e_d:        t_str = f"~{e_l.strftime('%H:%M')}"
            else:                   t_str = "종일"
            res_map.setdefault(cur, []).append(f"• [{room_name}] {r.title} ({t_str})")
            cur += timedelta(days=1)
 
    # ── 날짜별 데이터 행 출력 ────────────────────
    DAY_KR = ['월', '화', '수', '목', '금', '토', '일']
    cur_date = start_date
    row_num  = 3
    alt      = False
 
    while cur_date <= end_date:
        day_type = _get_day_type(cur_date)
        hol_name = get_holiday_name(cur_date)
        pmtc     = cohort_map.get(cur_date, [])
        res      = res_map.get(cur_date, [])
 
        # 배경색 결정 (우선순위: 공휴일 > 토요일 > PMTC > 예약)
        if day_type == 'holiday':   bg = COLOR_HOLIDAY_BG
        elif day_type == 'sat':     bg = COLOR_SAT_BG
        elif pmtc:                  bg = COLOR_COHORT_BG
        elif res:                   bg = COLOR_RES_BG
        else:                       bg = 'F9F9F9' if alt else 'FFFFFF'
 
        ws.row_dimensions[row_num].height = max(22, 15 + (len(pmtc) + len(res)) * 14)
 
        fg_day = 'A50000' if day_type == 'holiday' else ('003366' if day_type == 'sat' else '333333')
 
        # A열: 일자
        ca = ws.cell(row=row_num, column=1, value=cur_date.strftime('%Y-%m-%d'))
        # B열: 요일
        day_str = DAY_KR[cur_date.weekday()]
        if hol_name: day_str += f"\n({hol_name})"
        cb = ws.cell(row=row_num, column=2, value=day_str)
        
        for cell in (ca, cb):
            cell.fill      = _fill(bg)
            cell.alignment = _center(wrap=True)
            cell.border    = _thin_border()
            cell.font      = Font(name='맑은 고딕', size=10, color=fg_day)
 
        # C열: PMTC 일정
        cc = ws.cell(row=row_num, column=3, value="\n".join(pmtc) if pmtc else "")
        cc.fill      = _fill(bg)
        cc.alignment = Alignment(horizontal='left', vertical='center', wrap_text=True, indent=1)
        cc.border    = _thin_border()
        cc.font      = Font(name='맑은 고딕', size=9, bold=True, color='7C5600' if pmtc else 'AAAAAA')
 
        # D열: 강의실 예약
        cd = ws.cell(row=row_num, column=4, value="\n".join(res) if res else "-")
        cd.fill      = _fill(bg)
        cd.alignment = Alignment(horizontal='left', vertical='center', wrap_text=True, indent=1)
        cd.border    = _thin_border()
        cd.font      = Font(name='맑은 고딕', size=9, color='203764' if res else 'CCCCCC')
 
        alt = not alt
        cur_date += timedelta(days=1)
        row_num  += 1
 
    ws.freeze_panes = 'A3'
    return ws


# ──────────────────────────────────────────────────────────
# [4] 달력형 시트 빌더 (월별)
# ──────────────────────────────────────────────────────────
def _build_calendar_sheet(wb, year, month, reservations, cohort_list):
    ws = wb.create_sheet(title=f"{year}년 {month}월")
    
    # [컬러셋 - 컨설팅 테마]
    COLOR_CAL_TITLE = '1F3864'
    COLOR_WEEKDAY_HDR = '4472C4'
    COLOR_COHORT_BAR = 'FFF2CC'
    
    today = date.today()
    DAY_NAMES = ['일', '월', '화', '수', '목', '금', '토']
 
    for i in range(7):
        ws.column_dimensions[get_column_letter(i + 1)].width = 28
 
    # 1행: 제목
    ws.merge_cells('A1:G1')
    t = ws['A1']
    t.value     = f"{year}년 {month}월  교육장 운영 일정"
    t.font      = Font(name='맑은 고딕', size=15, bold=True, color='FFFFFF')
    t.fill      = _fill(COLOR_CAL_TITLE)
    t.alignment = _center()
    ws.row_dimensions[1].height = 40
 
    # 2행: 요일 헤더
    for ci, dn in enumerate(DAY_NAMES, 1):
        cell = ws.cell(row=2, column=ci, value=dn)
        bg = '800000' if ci == 1 else (COLOR_CAL_TITLE if ci == 7 else COLOR_WEEKDAY_HDR)
        cell.font      = Font(name='맑은 고딕', size=11, bold=True, color='FFFFFF')
        cell.fill      = _fill(bg)
        cell.alignment = _center()
        cell.border    = _thin_border()
    ws.row_dimensions[2].height = 25
 
    # 데이터 맵 (기수+주차 정보)
    cohort_map = {}
    for c in cohort_list:
        d = c.start_date
        while d <= c.end_date:
            week_num = (d - c.start_date).days // 7 + 1
            cohort_map.setdefault(d, []).append(f"🏫 PMTC ({c.name}기) ({week_num}W)")
            d += timedelta(days=1)
 
    res_map = {}
    for r in reservations:
        s_l = timezone.localtime(r.start_time)
        e_l = timezone.localtime(r.end_time)
        s_d, e_d = s_l.date(), e_l.date()
        cur = s_d
        while cur <= e_d:
            if cur == s_d == e_d: t_str = f"{s_l.strftime('%H:%M')}~{e_l.strftime('%H:%M')}"
            elif cur == s_d:      t_str = f"{s_l.strftime('%H:%M')}~"
            elif cur == e_d:      t_str = f"~{e_l.strftime('%H:%M')}"
            else:                 t_str = "종일"
            room_name = r.room.name if r.room else "?"
            res_map.setdefault(cur, []).append(f"[{room_name}] {t_str} {r.title}")
            cur += timedelta(days=1)
 
    # 달력 레이아웃 설정
    first_day_obj = date(year, month, 1)
    first_col = (first_day_obj.weekday() + 1) % 7 
    days_in_month = calendar.monthrange(year, month)[1]
    
    ROW_DATE_H = 22
    ROW_CONT_H = 110
    excel_row  = 3
    col        = first_col + 1
 
    def set_empty(er, ec):
        for ro in range(2):
            c = ws.cell(row=er + ro, column=ec)
            c.fill   = _fill('F9F9F9')
            c.border = _thin_border()
 
    def set_day(er, ec, cal_date):
        dt = _get_day_type(cal_date)
        hol_name = get_holiday_name(cal_date)
        pmtc = cohort_map.get(cal_date, [])
        res  = res_map.get(cal_date, [])
        is_today = (cal_date == today)
 
        # 칸 배경색
        if dt == 'holiday': bg = 'FFF2F2'
        elif dt == 'sat':   bg = 'F2F7FF'
        elif is_today:      bg = 'FFFFE1'
        else:               bg = 'FFFFFF'
 
        # 1. 날짜 줄 (번호 + 공휴일명)
        fg_n = 'A50000' if dt == 'holiday' else ('003366' if dt == 'sat' else '333333')
        date_label = str(cal_date.day)
        if hol_name: date_label += f" ({hol_name})"
        
        nc = ws.cell(row=er, column=ec, value=date_label)
        nc.font      = Font(name='맑은 고딕', size=9, bold=is_today, color=fg_n)
        nc.fill      = _fill(bg)
        nc.alignment = Alignment(horizontal='right', vertical='center', indent=1)
        nc.border    = Border(left=Side(style='thin', color='CCCCCC'), right=Side(style='thin', color='CCCCCC'), top=Side(style='thin', color='CCCCCC'))
 
        # 2. 내용 줄 (기수정보 + 예약정보)
        full_content = []
        if pmtc:
            full_content.append(" ▶ " + "\n ▶ ".join(pmtc))
        if res:
            full_content.append(" • " + "\n • ".join(res))
            
        cc = ws.cell(row=er + 1, column=ec, value="\n".join(full_content))
        cc.fill      = _fill(bg)
        cc.alignment = _top_left()
        cc.border    = Border(left=Side(style='thin', color='CCCCCC'), right=Side(style='thin', color='CCCCCC'), bottom=Side(style='thin', color='CCCCCC'))
        
        # 기수가 있으면 배경색을 기수색으로 덮어씀 (시인성)
        if pmtc:
            nc.fill = _fill(COLOR_CO_BG := 'FFF9E5')
            cc.fill = _fill(COLOR_CO_BG)
            cc.font = Font(name='맑은 고딕', size=8.5, color='203764')
        else:
            cc.font = Font(name='맑은 고딕', size=8.5, color='444444')
 
    ws.row_dimensions[excel_row].height = ROW_DATE_H
    ws.row_dimensions[excel_row + 1].height = ROW_CONT_H
    
    # 시작 전 빈칸
    for c in range(1, col): set_empty(excel_row, c)
 
    for day in range(1, days_in_month + 1):
        set_day(excel_row, col, date(year, month, day))
        col += 1
        if col > 7:
            col = 1; excel_row += 2
            if day < days_in_month:
                ws.row_dimensions[excel_row].height = ROW_DATE_H
                ws.row_dimensions[excel_row + 1].height = ROW_CONT_H
 
    # 끝난 후 빈칸
    if col > 1:
        for c in range(col, 8): set_empty(excel_row, c)
 
    ws.sheet_view.zoomScale = 100
    return ws
 
 
# ──────────────────────────────────────────────────────────
# [5] Django View
# ──────────────────────────────────────────────────────────
@login_required
def export_facility_schedule_excel(request):
    if not request.user.is_staff:
        return HttpResponse("권한이 없습니다. (관리자 전용)", status=403)
 
    start_date_str = request.GET.get('start_date')
    end_date_str   = request.GET.get('end_date')
    export_format  = request.GET.get('export_format', 'calendar')
 
    if not start_date_str or not end_date_str:
        return HttpResponse("시작일과 종료일을 선택해주세요.", status=400)
 
    start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
    end_date   = datetime.strptime(end_date_str,   '%Y-%m-%d').date()
    if start_date > end_date:
        return HttpResponse("오류: 종료일이 시작일보다 빠릅니다.", status=400)
 
    # DB 데이터
    reservations = Reservation.objects.filter(
        start_time__date__lte=end_date,
        end_time__date__gte=start_date,
        status='confirmed'
    ).select_related('room', 'user__profile').order_by('start_time')
 
    cohort_list = []
    try:
        from accounts.models import Cohort
        cohort_list = list(
            Cohort.objects.filter(start_date__lte=end_date, end_date__gte=start_date)
        )
    except Exception:
        pass
 
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
 
    # ★ 달력형과 목록형 모두 월(Month) 단위로 쪼개서 시트를 생성하도록 변경!
    cur = start_date.replace(day=1)
    while cur <= end_date:
        y, m = cur.year, cur.month
        next_m = cur.replace(month=m + 1) if m < 12 else cur.replace(year=y + 1, month=1)
        
        if export_format == 'list':
            # 해당 월에 속하는 날짜 구간만 자르기
            m_start = max(start_date, cur)
            m_end = min(end_date, next_m - timedelta(days=1))
            
            # 해당 월의 예약만 걸러내기
            m_res = [r for r in reservations if timezone.localtime(r.start_time).date() <= m_end and timezone.localtime(r.end_time).date() >= m_start]
            _build_list_sheet(wb, y, m, m_start, m_end, m_res, cohort_list)
        else:
            # 달력형 생성
            month_res = [r for r in reservations
                         if timezone.localtime(r.start_time).date() < next_m
                         and timezone.localtime(r.end_time).date() >= cur]
            _build_calendar_sheet(wb, y, m, month_res, cohort_list)
            
        cur = next_m
 
    suffix   = "배포용_일정표" if export_format == 'list' else "달력형_일정표"
    filename = f"{suffix}_{start_date_str}_{end_date_str}.xlsx"
    encoded  = urllib.parse.quote(filename)
 
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f"attachment; filename*=UTF-8''{encoded}"
    wb.save(response)
    return response

import json
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_GET
from django.db import transaction
from django.db.models import Q
from .models import Quiz, TestResult, StudentLog
from accounts.models import Profile # (Profile 위치에 맞게 import)

@login_required
@require_GET
def get_manual_exam_targets(request):
    """응시 대상자 필터링 (수정 불가 락 & 면담 미완료 락 적용)"""
    cohort_id = request.GET.get('cohort_id')
    quiz_id = request.GET.get('quiz_id')
    attempt = int(request.GET.get('attempt', 1))

    base_profiles = Profile.objects.filter(
        cohort_id=cohort_id, is_manager=False, is_pl=False, status__in=['attending', 'caution', 'counseling']
    ).select_related('user', 'company', 'process')

    # ★★★ [핵심 추가] 매니저는 '본인 공정' 학생만 봅니다! (최고관리자는 전체 다 봄) ★★★
    if not request.user.is_superuser:
        if hasattr(request.user, 'profile') and request.user.profile.process:
            base_profiles = base_profiles.filter(process=request.user.profile.process)

    data = []
    
    for p in base_profiles:
        existing_result = TestResult.objects.filter(user=p.user, quiz_id=quiz_id, attempt_number=attempt).first()
        is_already_entered = existing_result is not None
        existing_score = existing_result.score if existing_result else None

        if attempt == 1:
            data.append({
                'id': p.id, 'user_id': p.user.id, 'name': p.name, 'company': p.company.name if p.company else '-',
                'is_already_entered': is_already_entered, 'existing_score': existing_score, 'is_locked': False
            })
        else:
            prev_attempt = attempt - 1
            prev_result = TestResult.objects.filter(user=p.user, quiz_id=quiz_id, attempt_number=prev_attempt).first()
            
            if prev_result and not prev_result.is_pass:
                unresolved_log = StudentLog.objects.filter(
                    profile=p, related_quiz_id=quiz_id, log_type='exam_fail', stage=prev_attempt, is_resolved=False
                ).exists()
                
                data.append({
                    'id': p.id, 'user_id': p.user.id, 'name': p.name, 'company': p.company.name if p.company else '-',
                    'is_already_entered': is_already_entered, 'existing_score': existing_score, 'is_locked': unresolved_log
                })

    return JsonResponse({'status': 'success', 'data': data})

@login_required
@require_POST
def submit_manual_exam_scores(request):
    """점수 저장 및 누락자 자동 색출/알림 발송 (Bulk 처리 최적화)"""
    data = json.loads(request.body)
    cohort_id = data.get('cohort_id')
    quiz_id = data.get('quiz_id')
    attempt = int(data.get('attempt', 1))
    results = data.get('results', []) 

    quiz = Quiz.objects.get(id=quiz_id)
    pass_score = quiz.pass_score

    # ★ 최적화: 한 번에 DB에 밀어넣을 바구니(List) 준비
    test_results_to_create = []
    student_logs_to_create = []
    notifications_to_create = []
    profiles_to_update = []
    users_to_update = []

    # N+1 쿼리 방지: 필요한 학생들 정보 한방에 미리 다 가져오기
    user_ids = [res['user_id'] for res in results if res.get('score')]
    existing_results = set(TestResult.objects.filter(
        user_id__in=user_ids, quiz=quiz, attempt_number=attempt
    ).values_list('user_id', flat=True))
    
    profile_ids = [res['profile_id'] for res in results if res.get('score')]
    profiles_dict = {p.id: p for p in Profile.objects.filter(id__in=profile_ids).select_related('user', 'process')}
    
    superusers = list(User.objects.filter(is_superuser=True))
    managers_by_process = {}

    with transaction.atomic():
        for res in results:
            score_str = res.get('score')
            if not score_str: continue 
            
            user_id = int(res['user_id'])
            profile_id = int(res['profile_id'])
            score = float(score_str)

            if user_id in existing_results: continue

            is_pass = score >= pass_score
            profile = profiles_dict.get(profile_id)

            # 1. 성적 바구니에 담기
            test_results_to_create.append(
                TestResult(user_id=user_id, quiz=quiz, attempt_number=attempt, score=score, is_pass=is_pass)
            )

            if not is_pass:
                if attempt < 3:
                    reason_msg = f"[{quiz.title}] {attempt}차 평가 불합격 - 재응시 잠금"
                    if attempt == 2: reason_msg += " (PL 면담 필요)"

                    # 2. 학생 로그 바구니에 담기
                    student_logs_to_create.append(
                        StudentLog(profile=profile, recorder=request.user, log_type='exam_fail',
                                   reason=reason_msg, related_quiz=quiz, stage=attempt, is_resolved=False)
                    )
                    
                    # 수신자(매니저) 리스트 캐싱
                    receivers = set(superusers)
                    if profile.process:
                        if profile.process.id not in managers_by_process:
                            managers_by_process[profile.process.id] = list(User.objects.filter(is_staff=True, profile__is_manager=True, profile__process=profile.process))
                        receivers.update(managers_by_process[profile.process.id])
                        
                    # 3. 알림 바구니에 담기
                    target_url = f"/quiz/manager/trainees/{profile.id}/logs/"
                    for recv in receivers:
                        notifications_to_create.append(
                            Notification(recipient=recv, sender=request.user, notification_type='counseling', related_url=target_url,
                                         message=f"🚨 {profile.name}님 '{quiz.title}' 불합격! 면담(잠금 해제) 기록이 필요합니다.")
                        )
                elif attempt == 3:
                    profile.status = 'dropout'
                    profiles_to_update.append(profile)

                    profile.user.is_active = False
                    users_to_update.append(profile.user)

                    student_logs_to_create.append(
                        StudentLog(profile=profile, recorder=request.user, log_type='exam_fail',
                                   reason=f"{quiz.title} 3차 수기 시험 과락으로 인한 자동 퇴소 및 계정 정지 처리",
                                   related_quiz=quiz, stage=3, is_resolved=False)
                    )

        # ★★★ [하이라이트] 바구니에 모은 데이터 한방에 DB로 전송 (벌크 인서트/업데이트) ★★★
        if test_results_to_create: TestResult.objects.bulk_create(test_results_to_create)
        if student_logs_to_create: StudentLog.objects.bulk_create(student_logs_to_create)
        if notifications_to_create: Notification.objects.bulk_create(notifications_to_create)
        if profiles_to_update: Profile.objects.bulk_update(profiles_to_update, ['status'])
        if users_to_update: User.objects.bulk_update(users_to_update, ['is_active'])

        # 누락자 스캔 및 알림도 최적화
        if cohort_id:
            if attempt == 1:
                target_users = Profile.objects.filter(cohort_id=cohort_id, is_manager=False, is_pl=False, status__in=['attending', 'caution', 'counseling']).values_list('user_id', flat=True)
            else:
                prev_attempt = attempt - 1
                target_users = TestResult.objects.filter(quiz=quiz, attempt_number=prev_attempt, is_pass=False, user__profile__cohort_id=cohort_id).values_list('user_id', flat=True)
            
            entered_users = TestResult.objects.filter(quiz=quiz, attempt_number=attempt).values_list('user_id', flat=True)
            missing_users = set(target_users) - set(entered_users)
            
            # 누락자 알림 바구니에 담기
            missing_notifications = []
            if missing_users:
                missing_profiles = Profile.objects.filter(user_id__in=missing_users)
                for missing_profile in missing_profiles:
                    missing_notifications.append(
                        Notification(recipient=request.user, sender=request.user, notification_type='exam',
                                     message=f"⚠️ [점수 누락] '{missing_profile.name}' 교육생의 {attempt}차 점수가 입력되지 않았습니다!",
                                     related_url=f"/quiz/manager/trainees/{missing_profile.id}/")
                    )
                if missing_notifications: Notification.objects.bulk_create(missing_notifications)

    return JsonResponse({'status': 'success', 'message': '채점 점수가 안전하게 저장되었습니다. (누락자는 알림 센터로 발송됨)'})