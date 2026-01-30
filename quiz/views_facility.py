# quiz/views_facility.py

from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from django.db.models import Count
from .models import Room, Reservation, Notification # 모델 임포트 필수!

# accounts 앱의 모델 가져오기 (없으면 에러나니 꼭 확인)
try:
    from accounts.models import Profile, Process
except ImportError:
    # 혹시 모를 에러 방지용 더미 클래스
    Profile = None
    Process = None

# [헬퍼] 알림 발송
def send_notification(user, message):
    if user:
        Notification.objects.create(recipient=user, message=message)

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
    today = timezone.now()
    
    # 1. 이번 달 통계 데이터
    start_month = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    company_stats = Reservation.objects.filter(start_time__gte=start_month, status='confirmed').values('company_name').annotate(count=Count('id')).order_by('-count')
    process_stats = Reservation.objects.filter(start_time__gte=start_month, status='confirmed').values('process_name').annotate(count=Count('id')).order_by('-count')
    
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
    my_notifications = Notification.objects.filter(recipient=request.user, is_read=False).order_by('-created_at')
    is_manager = request.user.is_superuser or request.user.groups.filter(name='FacilityManager').exists()

    context = {
        'rooms': rooms,
        'company_stats': company_stats,
        'process_stats': process_stats,
        'today_reservations': today_reservations, # 이제 그룹화된 리스트가 넘어갑니다
        'is_manager': is_manager,
        'notifications': my_notifications,
    }
    return render(request, 'quiz/manager/facility_dashboard.html', context)

@login_required
def facility_events(request):
    # 1. 파라미터 가져오기
    start = safe_parse_datetime(request.GET.get('start'))
    end = safe_parse_datetime(request.GET.get('end'))
    room_id = request.GET.get('room_id')

    events = []
    if start and end:
        # 2. 날짜 범위 필터링
        query = Reservation.objects.filter(start_time__gte=start, end_time__lte=end)
        
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
        # 1. 최고 관리자 (Superuser)
        is_superuser = request.user.is_superuser
        # 2. 이 방의 지정 매니저 (Designated Manager)
        is_designated_manager = request.user in e.room.managers.all()
        # 3. 예약 당사자 (Owner)
        is_owner = (e.user == request.user)
        
        # [결재 권한] 승인/반려 가능 여부 (최고관리자 OR 지정매니저)
        can_approve = (is_superuser or is_designated_manager)
        
        # [편집 권한] 수정/삭제/드래그 가능 여부 (결재권자 OR 본인)
        can_edit = (can_approve or is_owner)

        data.append({
            'id': e.id,
            'room_id': e.room.id,
            'title': f"{prefix} - {e.title}",
            'start': e.start_time.isoformat(),
            'end': e.end_time.isoformat(),
            'color': color,
            
            # ★ [핵심] FullCalendar가 이 값을 보고 드래그 가능 여부를 결정합니다.
            'editable': can_edit, 

            'extendedProps': {
                'status_code': e.status, 
                'status_label': e.get_status_display(),
                'company': e.company_name, 
                'process': e.process_name,
                'username': user_name, 
                'full_desc': e.title,
                
                # 프론트엔드 버튼 제어용 플래그
                'is_admin': can_approve,    # 관리자 버튼(승인/반려) 보이기
                'can_approve': can_approve, # (이중 안전장치)
                'can_manage': can_edit,     # 수정/취소 버튼 보이기
                'can_edit': can_edit        # (이중 안전장치)
            }
        })
        
    return JsonResponse(data, safe=False)

# [3] 예약 신청 (알림 로직 수정: 지정 관리자에게 알림 발송)
@login_required
def facility_reserve(request):
    if request.method == 'POST':
        try:
            # 1. 수정인지 생성인지 확인 (ID가 있으면 수정)
            event_id = request.POST.get('id')
            
            # 2. 데이터 가져오기
            room = get_object_or_404(Room, pk=request.POST.get('room_id'))
            start_dt = safe_parse_datetime(request.POST.get('start_time'))
            end_dt = safe_parse_datetime(request.POST.get('end_time'))
            title = request.POST.get('title')

            if not start_dt or not end_dt: return JsonResponse({'status': 'error', 'message': '날짜 오류'})
            if start_dt >= end_dt: return JsonResponse({'status': 'error', 'message': '종료 시간이 더 빨라요!'})

            # 3. 권한 체크 (관리자 여부)
            is_approver = request.user.is_superuser or (request.user in room.managers.all())
            
            # [수정 모드]
            if event_id:
                res = get_object_or_404(Reservation, pk=event_id)
                
                # 권한 확인: 본인 또는 관리자만 수정 가능
                if not (is_approver or res.user == request.user):
                    return JsonResponse({'status': 'error', 'message': '수정 권한이 없습니다.'})
                
                res.room = room
                res.title = title
                res.start_time = start_dt
                res.end_time = end_dt
                # 관리자가 수정하면 확정 유지, 일반인은 다시 대기
                if not is_approver: 
                    res.status = 'pending' 
                
                action_type = "수정"

            # [생성 모드]
            else:
                res = Reservation(
                    room=room, user=request.user, title=title,
                    start_time=start_dt, end_time=end_dt,
                    status='confirmed' if is_approver else 'pending'
                )
                # 프로필 정보 추가
                try:
                    if hasattr(request.user, 'profile'):
                        p = request.user.profile
                        res.company_name = p.company.name if p.company else ''
                        res.process_name = p.process.name if p.process else ''
                except: pass
                
                action_type = "예약"

            # 4. 중복 체크 (자신을 제외하고 체크해야 함)
            # check_overlap 로직이 모델에 있다면, 수정 시 자기 자신은 제외하는 로직이 필요할 수 있음.
            # 여기서는 간단히 모델의 check_overlap을 호출하되, 
            # 만약 모델 메서드가 '자기 자신 제외'를 처리 안하면 수정 시 에러날 수 있음.
            # 안전하게: 
            overlapping = Reservation.objects.filter(
                room=room,
                start_time__lt=end_dt,
                end_time__gt=start_dt,
                status__in=['confirmed', 'pending'] # 반려된 건 중복 아님
            ).exclude(pk=res.pk if res.pk else None) # 자기 자신 제외

            if overlapping.exists():
                 return JsonResponse({'status': 'error', 'message': '해당 시간에 이미 예약이 있습니다.'})

            res.save()

            # 5. 알림 발송
            if not is_approver:
                msg = f"📢 [{action_type}] {request.user.first_name}님이 {room.name} 예약을 {action_type}했습니다."
                for mgr in room.managers.all():
                    if mgr != request.user: send_notification(mgr, msg)

            msg = f"{action_type} 되었습니다." + (" (승인 대기)" if not is_approver else "")
            return JsonResponse({'status': 'success', 'message': msg})

        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})
    return JsonResponse({'status': 'error'})

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
                event.status = 'pending'
                msg = '시간이 변경되었습니다. (관리자 재승인 필요)'
                # 지정 관리자에게 알림
                for mgr in event.room.managers.all():
                    send_notification(mgr, f"✏️ [수정] {event.title} 시간이 변경되었습니다. 확인해주세요.")
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
        if event.check_overlap(): return JsonResponse({'status': 'error', 'message': '승인 실패(중복)'})
        event.status = 'confirmed'
        event.save()
        send_notification(event.user, f"✅ 예약이 승인되었습니다: {event.title}")
        
        # 지정 관리자들에게도 확정 소식 공유 (본인 제외)
        for mgr in event.room.managers.all():
            if mgr != request.user:
                send_notification(mgr, f"🆗 [확정] {event.title} 예약이 승인처리 되었습니다.")

    elif action == 'reject':
        event.status = 'rejected'
        event.save()
        send_notification(event.user, f"❌ 예약이 반려되었습니다: {event.title}")

    elif action == 'delete':
        event.delete()
        if event.user != request.user: 
            send_notification(event.user, f"🗑 예약이 취소되었습니다: {event.title}")
        
    return JsonResponse({'status': 'success', 'message': '처리 완료'})