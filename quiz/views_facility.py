# quiz/views_facility.py

from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.utils.dateparse import parse_datetime
from datetime import timedelta
from django.utils import timezone
from django.db.models import Count
from .models import Room, Reservation, Notification # 모델 임포트 필수!

# accounts 앱의 모델 가져오기 (없으면 에러나니 꼭 확인)
try:
    from accounts.models import Profile, Process, Cohort,Company
except ImportError:
    # 혹시 모를 에러 방지용 더미 클래스
    Profile = None
    Process = None
    Cohort = None

# [헬퍼] 알림 발송
def send_notification(user, message):
    if user:
        # ★ 알림 생성 시 'facility' 꼬리표 달기
        Notification.objects.create(recipient=user, message=message, notification_type='facility')

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
    my_notifications = Notification.objects.filter(
        recipient=request.user, 
        is_read=False, 
        notification_type='facility'  # <--- 이 부분이 추가되었습니다.
    ).order_by('-created_at')
    is_manager = request.user.is_superuser or request.user.groups.filter(name='FacilityManager').exists()

    context = {
        'rooms': rooms,
        'company_stats': company_stats,
        'process_stats': process_stats,
        'today_reservations': today_reservations, 
        'is_manager': is_manager,
        'notifications': my_notifications,
        'companies': companies,
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
            # FullCalendar의 종일(allDay) 이벤트는 종료일을 하루 더해줘야 끝까지 예쁘게 채워집니다.
            c_end_plus_one = c.end_date + timedelta(days=1)
            
            data.append({
                'id': f'cohort_{c.id}',
                'title': f'🏫[ PMTC {c.name} 교육기간 ] ',
                'start': c.start_date.isoformat(),
                'end': c_end_plus_one.isoformat(),
                'color': '#ffecb5',      # 부드러운 노란색 배경
                'textColor': '#664d03',  # 진한 갈색 텍스트
                'allDay': True,          # ★ 달력 맨 위에 '종일' 띠로 고정시킴
                'editable': False,       # 마우스로 드래그 금지
                'extendedProps': {
                    'is_cohort': True    # 프론트에서 클릭 이벤트 방지용
                }
            })

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
    attendees=attendees,       # 이제 모델에 추가했으니 오류가 안 납니다!
    company_name=company_name, # 모델에 추가했는지 확인!
    status='confirmed' if is_approver else 'pending'
)
                    
                    # 중복 체크
                    if new_res.check_overlap():
                        return JsonResponse({'status': 'error', 'message': f'[{room.name}] 이미 예약된 시간입니다.'})
                    new_res.save()

                    # 관리자 알림 발송 (생략 가능)
                    if not is_approver:
                        msg = f"📢 [예약신청] {request.user.profile.name if hasattr(request.user, 'profile') else request.user.username}님이 {room.name} 예약을 신청했습니다."
                        for mgr in room.managers.all():
                            send_notification(mgr, msg)

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

# =========================================================
# ★ [추가] 알림 관련 기능 (삭제, 전체삭제, API)
# =========================================================

@login_required
def notification_read(request, noti_id):
    if int(noti_id) == 0: return JsonResponse({'status': 'success'}) # 시스템 가짜 알림은 무시
    noti = get_object_or_404(Notification, id=noti_id, recipient=request.user)
    noti.is_read = True
    noti.save()
    return JsonResponse({'status': 'success'})

@login_required
def notification_delete(request, noti_id):
    if int(noti_id) == 0: return JsonResponse({'status': 'success'}) # 시스템 가짜 알림은 무시
    noti = get_object_or_404(Notification, id=noti_id, recipient=request.user)
    noti.delete()
    return JsonResponse({'status': 'success'})

@login_required
def notification_clear_all(request):
    Notification.objects.filter(recipient=request.user).delete()
    return JsonResponse({'status': 'success'})

@login_required
def notification_api_list(request):
    """상단 벨 아이콘용 알림 목록 API (+ 5일 지난 알림 자동 청소 & 평가 대기 알림 생성)"""
    
    # 1. 5일이 지난 일반 알림은 자동 청소
    expiration_date = timezone.now() - timedelta(days=5)
    Notification.objects.filter(recipient=request.user, created_at__lt=expiration_date).delete()

    # =========================================================
    # ★ [핵심] 평가 대기 인원 '진짜 개별 알림' 자동 생성 로직
    # =========================================================
    if request.user.is_staff:
        today = timezone.now().date()
        
        # 평가를 받아야 하는(기수 종료되었으나 재직중인) 대상자 모두 찾기
        pending_profiles = Profile.objects.filter(
            cohort__end_date__lt=today,
            status__in=['attending', 'caution', 'counseling']
        ).exclude(user__is_superuser=True).exclude(is_manager=True).select_related('cohort', 'process')

        if not request.user.is_superuser:
            if hasattr(request.user, 'profile') and request.user.profile.process:
                pending_profiles = pending_profiles.filter(process=request.user.profile.process)
            else:
                # 공정이 할당되지 않은 일반 스태프는 알림을 받지 않음
                pending_profiles = pending_profiles.none()
        # =====================================================

        from django.urls import reverse

        for p in pending_profiles:
            # (이하 기존 코드 동일)
            cohort_name = p.cohort.name if p.cohort else "미지정"
            process_name = p.process.name if p.process else "미지정"
            days_passed = (today - p.cohort.end_date).days

            # 대상자별 최종 평가서 주소
            target_url = reverse('quiz:evaluate_trainee', args=[p.id])

            # 알림 메시지 세팅 (지연 일수에 따라 독촉 메시지로 변경)
            if days_passed <= 1:
                msg = f"[{cohort_name}/{process_name}] {p.name}님 기수가 종료되었습니다. 상세 페이지에서 최종 평가 및 수료 처리를 진행해주세요."
            else:
                msg = f"🚨 [D+{days_passed}일 지연] [{cohort_name}/{process_name}] {p.name}님 수료 처리가 안되었습니다! 즉시 작성 부탁드립니다."

            # 이 매니저에게 이 학생에 대한 알림이 이미 있는지 확인
            existing_noti = Notification.objects.filter(
                recipient=request.user,
                notification_type='pending_eval',
                related_url=target_url
            ).first()

            if not existing_noti:
                # 알림이 없으면 새로 생성 (DB에 진짜로 저장됨)
                Notification.objects.create(
                    recipient=request.user,
                    message=msg,
                    related_url=target_url,
                    notification_type='pending_eval'
                )
            else:
                # 이미 알림이 있는데 날짜가 어제 것이라면? -> 오늘 날짜로 갱신하고 다시 띄움! (독촉)
                if existing_noti.created_at.date() < today:
                    existing_noti.message = msg
                    existing_noti.is_read = False # 다시 안 읽음 상태로 (빨간 점 켜짐)
                    existing_noti.created_at = timezone.now() # 최상단으로 끌어올림
                    existing_noti.save()

    # =========================================================
    # 2. 안 읽은 알림 목록 화면에 전송
    # =========================================================
    notis = Notification.objects.filter(recipient=request.user, is_read=False).order_by('-created_at')
    count = notis.count()
    
    data = []
    for n in notis:
        icon = 'bi-info-circle text-primary'
        if n.notification_type == 'facility': icon = 'bi-building text-success'
        elif n.notification_type == 'signup': icon = 'bi-person-plus-fill text-info'
        elif n.notification_type == 'exam': icon = 'bi-pencil-square text-warning'
        # ★ 평가 대기 알림 아이콘
        elif n.notification_type == 'pending_eval': icon = 'bi-exclamation-square-fill text-danger'

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
        