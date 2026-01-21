from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
import calendar
from datetime import datetime, date, timedelta
import json
import math  # [수정] 거리 계산(Haversine)을 위해 필수 추가
from django.db.models import Q, Sum

# [필수] 공휴일 라이브러리
try:
    import holidays
except ImportError:
    holidays = None

# 모델 Import
from accounts.models import Profile, Process, Cohort, PartLeader
from quiz.models import StudentLog  # [추가] 알림 발송용
from .models import WorkType, DailySchedule, ScheduleRequest, Attendance 


# ------------------------------------------------------------------
# [Helper] 연차 발생 개수 계산 함수 (근속연수 기준)
# ------------------------------------------------------------------
def calculate_annual_leave_total(profile, target_year):
    """
    입사일(joined_at) 기준으로 해당 연도의 총 연차 개수를 계산합니다.
    """
    if not profile.joined_at:
        return 15  # 입사일 없으면 기본값
    
    # 근속 연수 계산 (대상 년도 - 입사 년도)
    years_worked = target_year - profile.joined_at.year
    
    if years_worked < 1:
        return 15  # 1년차 미만
    
    # 가산 연차 계산: (근속연수 - 1) // 2
    added_days = (years_worked - 1) // 2
    if added_days < 0: added_days = 0
    
    total = 15 + int(added_days)
    
    # 최대 25개 제한 (근로기준법)
    return min(total, 25)


# ------------------------------------------------------------------
# [Helper] 스케줄 수정 권한 확인
# ------------------------------------------------------------------
def can_manage_schedule(user, target_profile):
    if user.is_superuser:
        return True
    
    if hasattr(user, 'profile') and user.profile.is_manager:
        if user.profile.process == target_profile.process:
            return True
            
    return False


# ------------------------------------------------------------------
# [Helper] 거리 계산 함수 (Haversine 공식)
# ------------------------------------------------------------------
def calculate_distance(lat1, lon1, lat2, lon2):
    """Haversine 공식을 이용한 거리 계산 (단위: km)"""
    R = 6371  # 지구 반지름 (km)
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = math.sin(d_lat / 2) * math.sin(d_lat / 2) + \
        math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * \
        math.sin(d_lon / 2) * math.sin(d_lon / 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


# ------------------------------------------------------------------
# 1. [신규] 스마트 출근 인증 (GPS + MDM/Camera Block)
# ------------------------------------------------------------------
@login_required
@require_POST
def process_attendance(request):
    """
    [신규] 출근 인증 처리 (AJAX 요청)
    - 프론트엔드에서 1차 검증(GPS, 카메라 차단) 후 넘어온 데이터 저장
    """
    try:
        # 1. 오늘 이미 출근했는지 확인
        today = timezone.now().date()
        if Attendance.objects.filter(user=request.user, date=today).exists():
             return JsonResponse({'status': 'fail', 'message': '이미 오늘의 출근 기록이 존재합니다.'})

        # 2. 출근 기록 저장
        Attendance.objects.create(
            user=request.user,
            date=today,
            check_in_time=timezone.now(),
            status='출근', 
            is_verified=True # 인증 성공 표시
        )
        
        # (선택) DailySchedule에도 '출근' 상태 반영 (필요 시 주석 해제)
        # schedule, created = DailySchedule.objects.get_or_create(
        #     profile=request.user.profile, date=today,
        #     defaults={'work_type': WorkType.objects.get(name='정상')}
        # )
        
        return JsonResponse({'status': 'success', 'message': '출근 인증이 완료되었습니다! 오늘도 화이팅하세요.'})

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': f'시스템 오류: {str(e)}'})

# (구버전 호환용)
@login_required
def upload_mdm(request):
    return redirect('attendance:mdm_status') 

@login_required
def mdm_status(request):
    return render(request, 'attendance/index.html') 


# ------------------------------------------------------------------
# 2. 캘린더 스케줄 조회 (공유, 연차 계산, 필터)
# ------------------------------------------------------------------
@login_required
def schedule_index(request):
    today = timezone.now().date()
    try:
        year = int(request.GET.get('year', today.year))
        month = int(request.GET.get('month', today.month))
    except ValueError:
        year, month = today.year, today.month
    
    kr_holidays = holidays.KR(years=year) if holidays else {}
    _, num_days = calendar.monthrange(year, month)
    days_in_month = []
    weekday_map = {0:'월', 1:'화', 2:'수', 3:'목', 4:'금', 5:'토', 6:'일'}

    for day in range(1, num_days + 1):
        d = date(year, month, day)
        days_in_month.append({
            'day': day, 
            'date_str': d.strftime('%Y-%m-%d'),
            'weekday': weekday_map[d.weekday()],
            'is_weekend': d.weekday() >= 5,
            'is_holiday': d in kr_holidays,
            'holiday_name': kr_holidays.get(d, ''),
            'is_today': d == today
        })

    user = request.user
    # 1. 기본 대상: 재직 중인 사람 (User 조인)
    profiles = Profile.objects.select_related('cohort', 'process', 'user').filter(status='attending').exclude(name__isnull=True).exclude(name='')

    # 2. 관리자/매니저 권한 확인
    is_manager_or_admin = user.is_superuser or (hasattr(user, 'profile') and (user.profile.is_manager or user.profile.is_pl))

    # 3. 필터 값 가져오기
    sel_role = request.GET.get('role', 'student')
    sel_cohort = request.GET.get('cohort', '')
    sel_process = request.GET.get('process', '')

    if is_manager_or_admin:
        # [관리자/매니저 모드]
        if sel_role == 'manager':
            # 매니저, PL, 슈퍼유저, 스태프 중 하나라도 해당되면 포함
            profiles = profiles.filter(
                Q(is_manager=True) | 
                Q(is_pl=True) | 
                Q(user__is_superuser=True) | 
                Q(user__is_staff=True)
            )
        else:
            # 순수 교육생만 보기
            profiles = profiles.filter(
                is_manager=False, is_pl=False, user__is_superuser=False, user__is_staff=False
            )

        if sel_cohort: profiles = profiles.filter(cohort_id=sel_cohort)
        if sel_process: profiles = profiles.filter(process_id=sel_process)
        
    else:
        # [교육생 모드]
        sel_role = 'student'
        profiles = profiles.filter(is_manager=False, is_pl=False, user__is_superuser=False)
        
        if hasattr(user, 'profile'):
            # 같은 공정(반)인 동료들은 모두 보여줌
            if user.profile.process:
                profiles = profiles.filter(process=user.profile.process)
            else:
                # 공정이 없으면 본인만
                profiles = profiles.filter(user=user)
        else:
            profiles = profiles.none()

    profiles = profiles.order_by('name')

    # [연차 계산 로직]
    current_year_start = date(year, 1, 1)
    current_year_end = date(year, 12, 31)

    leave_usage_map = {}
    if profiles.exists():
        usage_data = DailySchedule.objects.filter(
            profile__in=profiles,
            date__range=(current_year_start, current_year_end)
        ).values('profile').annotate(used_total=Sum('work_type__deduction'))

        for item in usage_data:
            leave_usage_map[item['profile']] = item['used_total'] or 0

    schedule_map = {}
    start_date = date(year, month, 1)
    end_date = date(year, month, num_days)
    
    db_data = {}
    if profiles.exists():
        schedules = DailySchedule.objects.filter(
            profile__in=profiles, date__range=(start_date, end_date)
        ).select_related('work_type')

        for s in schedules:
            if s.profile_id not in db_data: db_data[s.profile_id] = {}
            db_data[s.profile_id][s.date.strftime('%Y-%m-%d')] = s.work_type

    for p in profiles:
        # [핵심] 입사일 기준 총 연차 계산 함수 호출
        total_leave = calculate_annual_leave_total(p, year)
        used = leave_usage_map.get(p.id, 0)
        remain = total_leave - used
        
        row_data = {
            'profile': p, 
            'daily_data': {}, 
            'stats': {
                'work':0, 'rest':0, 'leave':0, 'half':0, 'etc':0,
                'annual_remain': remain,      # 잔여
                'annual_total': total_leave   # 전체 (동적 계산됨)
            }
        }
        user_schedules = db_data.get(p.id, {})
        
        for day_info in days_in_month:
            d_str = day_info['date_str']
            if d_str in user_schedules:
                wt = user_schedules[d_str]
                row_data['daily_data'][d_str] = wt
                if wt.deduction == 1.0: row_data['stats']['leave'] += 1
                elif 0 < wt.deduction < 1.0: row_data['stats']['half'] += 1
                elif wt.is_working_day and wt.deduction == 0: row_data['stats']['work'] += 1
                else:
                    if not wt.is_working_day: row_data['stats']['rest'] += 1
                    else: row_data['stats']['etc'] += 1
            else:
                if day_info['is_weekend'] or day_info['is_holiday']:
                    row_data['daily_data'][d_str] = None
                    row_data['stats']['rest'] += 1 
                else:
                    row_data['daily_data'][d_str] = 'DEFAULT_F' 
                    row_data['stats']['work'] += 1
                    
        schedule_map[p.id] = row_data

    # 다음달 계산
    if today.month == 12: next_month_start = date(today.year + 1, 1, 1)
    else: next_month_start = date(today.year, today.month + 1, 1)

    context = {
        'year': year, 'month': month,
        'days_in_month': days_in_month,
        'schedule_map': schedule_map,
        'work_types': WorkType.objects.all().order_by('order'),
        'cohorts': Cohort.objects.all(),
        'processes': Process.objects.all(),
        'sel_cohort': int(sel_cohort) if sel_cohort else '',
        'sel_process': int(sel_process) if sel_process else '',
        'sel_role': sel_role,
        'prev_month': (start_date - timedelta(days=1)).strftime('%Y-%m'),
        'next_month': (end_date + timedelta(days=1)).strftime('%Y-%m'),
        'is_manager': is_manager_or_admin,
    }
    return render(request, 'attendance/schedule.html', context)


# ------------------------------------------------------------------
# 3. 스케줄 수정 (기존 로직 유지 - 매니저 본인 수정 시 승인 요청)
# ------------------------------------------------------------------
@login_required
@require_POST
def update_schedule(request):
    try:
        data = json.loads(request.body)
        profile_id = data.get('profile_id')
        date_str = data.get('date')
        work_type_id = data.get('work_type_id')
        reason = data.get('reason', '')

        target_profile = get_object_or_404(Profile, pk=profile_id)
        work_type = get_object_or_404(WorkType, pk=work_type_id)
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        
        is_owner = (target_profile.user == request.user)
        is_superuser = request.user.is_superuser
        
        is_manager_of_target = False
        if hasattr(request.user, 'profile') and request.user.profile.is_manager:
            if request.user.profile.process == target_profile.process:
                is_manager_of_target = True

        if not (is_owner or is_superuser or is_manager_of_target):
             return JsonResponse({'status': 'error', 'message': '수정 권한이 없습니다.'}, status=403)
        
        today = timezone.now().date()
        if today.month == 12: next_month_start = date(today.year + 1, 1, 1)
        else: next_month_start = date(today.year, today.month + 1, 1)

        # 1. 과거 수정 (~어제): 슈퍼유저만 가능
        if target_date < today:
            if is_superuser:
                DailySchedule.objects.update_or_create(
                    profile=target_profile, date=target_date, defaults={'work_type': work_type}
                )
                return JsonResponse({'status': 'success', 'message': '관리자 권한으로 과거 수정됨'})
            else:
                 return JsonResponse({'status': 'error', 'message': '지난 날짜는 관리자만 수정 가능합니다.'})

        # 2. 미래 수정 (다음달~): 누구나 즉시 수정
        elif target_date >= next_month_start:
            DailySchedule.objects.update_or_create(
                profile=target_profile, date=target_date, defaults={'work_type': work_type}
            )
            return JsonResponse({'status': 'success', 'message': '미래 근무 수정됨'})

        # 3. 당월 수정 (오늘~말일)
        else:
            # (A) 슈퍼유저 프리패스
            if is_superuser:
                DailySchedule.objects.update_or_create(
                    profile=target_profile, date=target_date, defaults={'work_type': work_type}
                )
                return JsonResponse({'status': 'success', 'message': '관리자 권한 수정'})

            # (B) 매니저가 '타인(교육생)' 수정 -> 프리패스
            if is_manager_of_target and not is_owner:
                DailySchedule.objects.update_or_create(
                    profile=target_profile, date=target_date, defaults={'work_type': work_type}
                )
                return JsonResponse({'status': 'success', 'message': '매니저 권한 수정'})

            # (C) 본인 수정 (교육생 OR 매니저 본인) -> 승인 요청 필수
            if not reason:
                return JsonResponse({'status': 'reason_required'})
            
            ScheduleRequest.objects.create(
                requester=target_profile, date=target_date,
                target_work_type=work_type, reason=reason, status='pending'
            )
            return JsonResponse({'status': 'request_sent', 'message': '승인 요청이 전송되었습니다.'})

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@login_required
def get_pending_requests(request):
    if not (request.user.is_staff or request.user.is_superuser):
        return JsonResponse({'requests': []})
    
    if request.user.is_superuser:
        requests = ScheduleRequest.objects.filter(status='pending')
    elif hasattr(request.user, 'profile') and request.user.profile.is_manager:
        my_process = request.user.profile.process
        requests = ScheduleRequest.objects.filter(
            requester__process=my_process, status='pending'
        ).exclude(requester=request.user.profile)
    else:
        return JsonResponse({'requests': []})
        
    data = [{'id': r.id, 'name': r.requester.name, 'date': r.date.strftime('%Y-%m-%d'), 'type': r.target_work_type.short_name, 'reason': r.reason} for r in requests]
    return JsonResponse({'requests': data})


@login_required
def process_request(request, request_id, action):
    """
    근무 변경 요청 승인(approve) / 반려(reject) 통합 처리
    """
    # 1. POST 요청만 허용 (보안)
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': '잘못된 접근입니다.'}, status=405)

    # 2. 관리자 권한 확인 (스태프 이상)
    if not request.user.is_staff:
        return JsonResponse({'status': 'error', 'message': '관리자 권한이 없습니다.'}, status=403)

    try:
        with transaction.atomic():
            req_obj = get_object_or_404(ScheduleRequest, id=request_id)
            
            # 이미 처리된 요청인지 확인
            if req_obj.status != 'pending':
                return JsonResponse({'status': 'error', 'message': '이미 처리된 요청입니다.'})

            # ============================================
            # [CASE 1] 승인 (Approve)
            # ============================================
            if action == 'approve':
                # 1) 상태 변경
                req_obj.status = 'approved'
                req_obj.approver = request.user
                req_obj.save()

                # 2) 근무표 실제 반영 (DailySchedule 업데이트)
                daily, created = DailySchedule.objects.get_or_create(
                    profile=req_obj.requester,  
                    date=req_obj.date
                )
                daily.work_type = req_obj.target_work_type
                daily.save()

                # 3) 알림 로그 생성 (★ recorder 필드명 수정됨)
                StudentLog.objects.create(
                    profile=req_obj.requester,
                    log_type='others', # 승인은 단순 알림 성격이므로 'others' 또는 'system'
                    reason=f"[근무변경 승인] {req_obj.date} 근무가 '{req_obj.target_work_type.short_name}'(으)로 변경되었습니다.",
                    is_resolved=True,
                    recorder=request.user # ★ [수정 완료] created_by -> recorder
                )
                
                return JsonResponse({'status': 'success', 'message': '승인이 완료되었습니다.'})

            # ============================================
            # [CASE 2] 반려 (Reject)
            # ============================================
            elif action == 'reject':
                req_obj.status = 'rejected'
                req_obj.approver = request.user
                req_obj.save()

                # 알림 로그 생성 (★ recorder 필드명 수정됨)
                StudentLog.objects.create(
                    profile=req_obj.requester,
                    log_type='warning', # 반려/거절은 주의 환기 차원에서 'warning' 사용 가능 (선택 사항)
                    reason=f"[근무변경 반려] {req_obj.date} 요청이 반려되었습니다. (사유: {req_obj.reason})",
                    is_resolved=True,
                    recorder=request.user # ★ [수정 완료] created_by -> recorder
                )

                return JsonResponse({'status': 'success', 'message': '요청이 반려되었습니다.'})

            else:
                return JsonResponse({'status': 'error', 'message': '알 수 없는 명령입니다.'})

    except Exception as e:
        print(f"❌ [에러발생] process_request 중 오류: {e}")
        return JsonResponse({'status': 'error', 'message': f'서버 오류 발생: {str(e)}'}, status=500)


# ------------------------------------------------------------------
# 5. 전체 정상 적용 (일괄 처리)
# ------------------------------------------------------------------
@login_required
@require_POST
def apply_all_normal(request):
    """평일 일괄 적용"""
    try:
        data = json.loads(request.body)
        year = int(data.get('year'))
        month = int(data.get('month'))
        profile_ids = data.get('profile_ids', [])
        
        if not (request.user.is_superuser or (hasattr(request.user, 'profile') and request.user.profile.is_manager)):
             return JsonResponse({'status': 'error', 'message': '권한이 없습니다.'}, status=403)

        # '정상'이 포함되고 차감이 0인 근무를 우선 찾음 (연차 선택 방지)
        normal_type = WorkType.objects.filter(name__contains="정상", deduction=0).first()
        if not normal_type: 
            normal_type = WorkType.objects.filter(deduction=0).exclude(name__contains="연차").order_by('order').first()
            
        if not normal_type:
            return JsonResponse({'status': 'error', 'message': '정상 근무 유형이 없습니다.'})
        
        kr_holidays = holidays.KR(years=year) if holidays else {}
        _, num_days = calendar.monthrange(year, month)
        create_list = []
        
        my_process = request.user.profile.process if hasattr(request.user, 'profile') else None
        
        for pid in profile_ids:
            target_profile = Profile.objects.get(pk=pid)
            if not request.user.is_superuser:
                if target_profile.process != my_process:
                    continue 

            for day in range(1, num_days + 1):
                curr_date = date(year, month, day)
                if curr_date.weekday() >= 5 or curr_date in kr_holidays:
                    continue

                if not DailySchedule.objects.filter(profile_id=pid, date=curr_date).exists():
                    create_list.append(DailySchedule(profile_id=pid, date=curr_date, work_type=normal_type))
        
        DailySchedule.objects.bulk_create(create_list)
        return JsonResponse({'status': 'success', 'count': len(create_list)})
        
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    

@login_required
def check_in_page(request):
    """출근 체크 화면을 보여주는 뷰"""
    return render(request, 'attendance/check_in.html')

@login_required
@csrf_exempt # JS에서 POST 요청을 편하게 보내기 위해 임시 허용 (보안 강화 시 제거 권장)
def check_in_api(request):
    """
    프론트엔드에서 보낸 좌표와 MDM 상태를 받아 출근 처리하는 API
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': '잘못된 접근입니다.'})

    try:
        data = json.loads(request.body)
        lat = float(data.get('lat', 0))
        lon = float(data.get('lon', 0))
        is_mdm_active = data.get('is_mdm_active', False) # True여야 출근 가능

        # 1. MDM 검사 (카메라가 차단되어 있어야 함)
        if not is_mdm_active:
            return JsonResponse({'status': 'fail', 'message': '보안 앱(MDM)이 감지되지 않았습니다. (카메라가 작동 중입니다)'})

        # 2. 위치 검사 (평택 캠퍼스 반경 300m)
        # 평택 캠퍼스 좌표 (예시: 삼성전자 평택캠퍼스 인근) - 실제 좌표로 수정 필요!
        CENTER_LAT = 37.027  # ⚠️ 실제 위도로 수정하세요
        CENTER_LON = 127.047 # ⚠️ 실제 경도로 수정하세요
        RADIUS_LIMIT = 0.3   # 300m = 0.3km

        distance = calculate_distance(lat, lon, CENTER_LAT, CENTER_LON)
        
        if distance > RADIUS_LIMIT:
            return JsonResponse({
                'status': 'fail', 
                'message': f'사업장 반경 {RADIUS_LIMIT*1000}m 이내에서만 출근 가능합니다.\n(현재 거리: {int(distance*1000)}m)'
            })

        # 3. 출근 기록 저장
        # 오늘 날짜의 DailySchedule 확인
        today = timezone.now().date()
        daily_schedule, _ = DailySchedule.objects.get_or_create(
            profile=request.user.profile,
            date=today
        )

        # 이미 출근했는지 확인
        if Attendance.objects.filter(daily_schedule=daily_schedule).exists():
            return JsonResponse({'status': 'fail', 'message': '이미 금일 출근 기록이 있습니다.'})

        # 출근 생성
        Attendance.objects.create(
            daily_schedule=daily_schedule,
            check_in_time=timezone.now(),
            status='present' # 우선 정상 출근으로 처리 (지각 로직은 리포트 발송 시 또는 여기서 추가 가능)
        )

        return JsonResponse({'status': 'success', 'message': '출근 인증이 완료되었습니다!'})

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})