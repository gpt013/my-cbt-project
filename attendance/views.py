from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone
import calendar
from datetime import datetime, date, timedelta
import json
from django.db.models import Q, Sum

# [필수] 공휴일 라이브러리
try:
    import holidays
except ImportError:
    holidays = None

# 모델 Import
from accounts.models import Profile, Process, Cohort, PartLeader
from .models import WorkType, DailySchedule, ScheduleRequest
from .utils import analyze_mdm_image

# ------------------------------------------------------------------
# [Helper] 연차 발생 개수 계산 함수 (근속연수 기준)
# ------------------------------------------------------------------
def calculate_annual_leave_total(profile, target_year):
    """
    입사일(joined_at) 기준으로 해당 연도의 총 연차 개수를 계산합니다.
    - 입사일 미입력 시: 기본 15개
    - 1년 미만: 11개 (여기선 편의상 15개로 설정)
    - 2년마다 1일씩 가산 (최대 25개)
    """
    if not profile.joined_at:
        return 15 # 입사일 없으면 기본값
    
    # 근속 연수 계산 (대상 년도 - 입사 년도)
    years_worked = target_year - profile.joined_at.year
    
    if years_worked < 1:
        return 15 # 1년차 미만
    
    # 가산 연차 계산: (근속연수 - 1) // 2
    # 예: 3년차(1개 추가), 5년차(2개 추가)
    added_days = (years_worked - 1) // 2
    if added_days < 0: added_days = 0
    
    total = 15 + int(added_days)
    
    # 최대 25개 제한 (근로기준법)
    return min(total, 25)


# ------------------------------------------------------------------
# [Helper] 스케줄 수정 권한 확인
# ------------------------------------------------------------------
def can_manage_schedule(user, target_profile):
    """
    해당 유저가 타겟 프로필의 스케줄을 즉시 수정할 권한(관리자/매니저)이 있는지 확인
    """
    if user.is_superuser:
        return True
    
    if hasattr(user, 'profile') and user.profile.is_manager:
        if user.profile.process == target_profile.process:
            return True
            
    return False


# ------------------------------------------------------------------
# 1. MDM 인증 (정상 기준 강화)
# ------------------------------------------------------------------
@login_required
def upload_mdm(request):
    today = timezone.now().date()
    schedule = DailySchedule.objects.filter(profile=request.user.profile, date=today).first()

    if request.method == 'POST' and request.FILES.get('mdm_image'):
        image_file = request.FILES['mdm_image']
        
        # 스케줄 없으면 '정상 근무'로 생성
        if not schedule:
            default_work = WorkType.objects.filter(name__contains="정상", deduction=0).first()
            if not default_work: default_work = WorkType.objects.filter(deduction=0).first()
            
            schedule = DailySchedule.objects.create(
                profile=request.user.profile, 
                date=today,
                work_type=default_work
            )
        
        schedule.mdm_image = image_file
        schedule.save()

        try:
            file_path = schedule.mdm_image.path
            is_valid_time, detected_time, is_violation = analyze_mdm_image(file_path)
            
            schedule.captured_time = detected_time
            
            # [수정] 비정상(파란색/해제)일 경우 저장하지 않고 경고
            if is_violation:
                schedule.is_mdm_verified = False
                messages.error(request, "🚨 [보안 위반] 파란색(해제) 화면이 감지되었습니다. 담당 매니저에게 직접 보고하세요.")
            elif not is_valid_time:
                schedule.is_mdm_verified = False
                msg = f"⏰ 시간 인증 실패. ({detected_time})" if detected_time else "⏰ 시간 인식 실패."
                messages.warning(request, msg + " 다시 찍거나 매니저에게 보고하세요.")
            else:
                schedule.is_mdm_verified = True
                if detected_time:
                    limit = detected_time.replace(hour=9, minute=0, second=0, microsecond=0)
                    schedule.is_late = (detected_time > limit)
                    if schedule.is_late:
                        messages.warning(request, "✅ 인증되었으나, 09:00가 넘어 '지각' 처리되었습니다.")
                    else:
                        messages.success(request, "✅ MDM 보안 인증 및 출석이 완료되었습니다.")
                else:
                    messages.success(request, "✅ MDM 보안 인증이 완료되었습니다.")

        except Exception as e:
            print(f"MDM Analysis Error: {e}")
            messages.error(request, "이미지 분석 중 오류가 발생했습니다.")

        schedule.save()
        return redirect('attendance:mdm_status')

    return render(request, 'attendance/upload_mdm.html', {'record': schedule})

@login_required
def mdm_status(request):
    logs = DailySchedule.objects.filter(profile=request.user.profile).order_by('-date')
    return render(request, 'attendance/mdm_status.html', {'logs': logs})


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
        # [교육생 모드 - 핵심 수정]
        sel_role = 'student'
        profiles = profiles.filter(is_manager=False, is_pl=False, user__is_superuser=False)
        
        if hasattr(user, 'profile'):
            # [수정] 같은 공정(반)인 동료들은 모두 보여줌
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
@require_POST
def process_request(request):
    try:
        data = json.loads(request.body)
        req = get_object_or_404(ScheduleRequest, pk=data.get('request_id'))
        
        can_approve = False
        if request.user.is_superuser:
            can_approve = True
        elif hasattr(request.user, 'profile') and request.user.profile.is_manager:
            if request.user.profile.process == req.requester.process:
                can_approve = True
        
        if not can_approve: return JsonResponse({'status': 'error', 'message': '권한이 없습니다.'}, status=403)

        if data.get('action') == 'approve':
            DailySchedule.objects.update_or_create(profile=req.requester, date=req.date, defaults={'work_type': req.target_work_type})
            req.status = 'approved'
        else:
            req.status = 'rejected'
        req.approver = request.user
        req.save()
        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


# ------------------------------------------------------------------
# [핵심 수정] 4. 전체 정상 적용 (버그 수정)
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

        # [수정] '정상'이 포함되고 차감이 0인 근무를 우선 찾음 (연차 선택 방지)
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