from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone
import calendar
from datetime import datetime, date, timedelta
import json
from django.db.models import Q,Sum

# [필수] 공휴일 라이브러리
try:
    import holidays
except ImportError:
    holidays = None

# [수정됨] 모델 Import 경로 수정 (accounts 앱 모델은 accounts.models에서 가져옴)
from accounts.models import Profile, Process, Cohort, PartLeader
from .models import WorkType, DailySchedule, ScheduleRequest
from .utils import analyze_mdm_image

# ------------------------------------------------------------------
# [Helper] 보안 검증 함수
# ------------------------------------------------------------------
def is_my_trainee(user, target_profile):
    if user.is_superuser:
        return True
    if hasattr(user, 'profile') and user.profile.is_pl:
        try:
            my_pl_identity = PartLeader.objects.get(email=user.email)
            return target_profile.pl == my_pl_identity
        except PartLeader.DoesNotExist:
            return False
    return False


# ------------------------------------------------------------------
# 1. MDM 인증 및 상태 확인 (upload_mdm 함수 포함)
# ------------------------------------------------------------------
@login_required
def upload_mdm(request):
    today = timezone.now().date()
    schedule = DailySchedule.objects.filter(profile=request.user.profile, date=today).first()

    if request.method == 'POST' and request.FILES.get('mdm_image'):
        image_file = request.FILES['mdm_image']
        
        # 스케줄이 없으면 새로 생성 (기본값: 정상근무)
        if not schedule:
            default_work = WorkType.objects.filter(name__contains="정상").first()
            schedule = DailySchedule.objects.create(
                profile=request.user.profile, 
                date=today,
                work_type=default_work
            )
        
        # 이미지 저장
        schedule.mdm_image = image_file
        schedule.save()

        # 이미지 분석 실행
        try:
            file_path = schedule.mdm_image.path
            is_valid_time, detected_time, is_violation = analyze_mdm_image(file_path)
            
            schedule.captured_time = detected_time
            
            if is_violation:
                schedule.is_mdm_verified = False
                messages.error(request, "🚨 [보안 위반] 파란색(해제) 화면이 감지되었습니다.")
            elif not is_valid_time:
                schedule.is_mdm_verified = False
                msg = f"⏰ 시간 인증 실패. (인식된 시간: {detected_time})" if detected_time else "⏰ 시간 인식 실패."
                messages.warning(request, msg + " 현재 시간이 보이게 다시 찍어주세요.")
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
# 2. 캘린더 스케줄 관리
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
    profiles = Profile.objects.select_related('cohort', 'process').filter(status='attending').exclude(name__isnull=True).exclude(name='')

    is_manager_or_admin = user.is_superuser or (hasattr(user, 'profile') and (user.profile.is_manager or user.profile.is_pl))

    if is_manager_or_admin:
        role_filter = request.GET.get('role', 'student')
        if role_filter == 'manager':
            profiles = profiles.filter(Q(is_manager=True) | Q(is_pl=True))
        else:
            profiles = profiles.filter(is_manager=False, is_pl=False)

        if request.GET.get('cohort'): profiles = profiles.filter(cohort_id=request.GET.get('cohort'))
        if request.GET.get('process'): profiles = profiles.filter(process_id=request.GET.get('process'))
    else:
        role_filter = 'student'
        profiles = profiles.filter(is_manager=False, is_pl=False)
        if hasattr(user, 'profile'):
            if user.profile.cohort: profiles = profiles.filter(cohort=user.profile.cohort)
            if user.profile.process: profiles = profiles.filter(process=user.profile.process)
            # 소속 정보가 없으면 본인만
            if not user.profile.cohort and not user.profile.process:
                profiles = profiles.filter(user=user)
        else:
            profiles = profiles.none()

    profiles = profiles.order_by('name')

    TOTAL_ANNUAL_LEAVE = 15 
    
    current_year_start = date(year, 1, 1)
    current_year_end = date(year, 12, 31)

    # 한 번의 쿼리로 조회된 인원들의 연차 사용량 집계
    leave_usage_map = {}
    usage_data = DailySchedule.objects.filter(
        profile__in=profiles,
        date__range=(current_year_start, current_year_end)
    ).values('profile').annotate(used_total=Sum('work_type__deduction'))

    for item in usage_data:
        leave_usage_map[item['profile']] = item['used_total'] or 0
        

    schedule_map = {}
    start_date = date(year, month, 1)
    end_date = date(year, month, num_days)
    
    schedules = DailySchedule.objects.filter(
        profile__in=profiles, date__range=(start_date, end_date)
    ).select_related('work_type')

    db_data = {}
    for s in schedules:
        if s.profile_id not in db_data: db_data[s.profile_id] = {}
        db_data[s.profile_id][s.date.strftime('%Y-%m-%d')] = s.work_type

    for p in profiles:
        # 연차 잔여 계산
        used = leave_usage_map.get(p.id, 0)
        remain = TOTAL_ANNUAL_LEAVE - used
        
        row_data = {
            'profile': p, 
            'daily_data': {}, 
            'stats': {
                'work':0, 'rest':0, 'leave':0, 'half':0, 'etc':0,
                'annual_remain': remain,  # 잔여 연차
                'annual_total': TOTAL_ANNUAL_LEAVE # 전체 연차
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

    if today.month == 12: next_month_start = date(today.year + 1, 1, 1)
    else: next_month_start = date(today.year, today.month + 1, 1)

    context = {
        'year': year, 'month': month,
        'days_in_month': days_in_month,
        'schedule_map': schedule_map,
        'work_types': WorkType.objects.all().order_by('order'),
        'cohorts': Cohort.objects.all(),
        'processes': Process.objects.all(),
        'sel_cohort': int(request.GET.get('cohort')) if request.GET.get('cohort') else '',
        'sel_process': int(request.GET.get('process')) if request.GET.get('process') else '',
        'sel_role': role_filter,
        'prev_month': (start_date - timedelta(days=1)).strftime('%Y-%m'),
        'next_month': (end_date + timedelta(days=1)).strftime('%Y-%m'),
        'is_manager': is_manager_or_admin,
    }
    return render(request, 'attendance/schedule.html', context)


# ------------------------------------------------------------------
# 3. 스케줄 수정 및 승인 시스템
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
        can_manage = is_my_trainee(request.user, target_profile)
        
        if not (is_owner or can_manage):
             return JsonResponse({'status': 'error', 'message': '수정 권한이 없습니다.'}, status=403)
        
        today = timezone.now().date()
        if today.month == 12: next_month_start = date(today.year + 1, 1, 1)
        else: next_month_start = date(today.year, today.month + 1, 1)

        if target_date < today:
            if not request.user.is_superuser:
                return JsonResponse({'status': 'error', 'message': '지난 날짜는 관리자만 수정 가능합니다.'})

        elif target_date >= next_month_start:
            pass 

        else:
            if not can_manage: 
                if not reason: return JsonResponse({'status': 'reason_required'})
                
                ScheduleRequest.objects.create(
                    requester=target_profile, date=target_date,
                    target_work_type=work_type, reason=reason, status='pending'
                )
                return JsonResponse({'status': 'request_sent', 'message': '승인 요청이 전송되었습니다.'})

        DailySchedule.objects.update_or_create(
            profile=target_profile, date=target_date,
            defaults={'work_type': work_type}
        )
        return JsonResponse({'status': 'success'})

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@login_required
def get_pending_requests(request):
    if not (request.user.is_staff and hasattr(request.user, 'profile') and request.user.profile.is_pl):
        return JsonResponse({'requests': []})
    
    try:
        pl_obj = PartLeader.objects.get(email=request.user.email)
        requests = ScheduleRequest.objects.filter(
            requester__pl=pl_obj, status='pending'
        ).select_related('requester', 'target_work_type').order_by('date')
        
        data = [{
            'id': r.id, 'name': r.requester.name, 
            'date': r.date.strftime('%Y-%m-%d'),
            'type': r.target_work_type.short_name, 'reason': r.reason
        } for r in requests]
        
        return JsonResponse({'requests': data})
    except PartLeader.DoesNotExist:
        return JsonResponse({'requests': []})


@login_required
@require_POST
def process_request(request):
    try:
        data = json.loads(request.body)
        req = get_object_or_404(ScheduleRequest, pk=data.get('request_id'))
        
        if not is_my_trainee(request.user, req.requester):
             return JsonResponse({'status': 'error', 'message': '타 공정 인원은 승인할 수 없습니다.'}, status=403)

        if data.get('action') == 'approve':
            DailySchedule.objects.update_or_create(
                profile=req.requester, date=req.date,
                defaults={'work_type': req.target_work_type}
            )
            req.status = 'approved'
        else:
            req.status = 'rejected'
        
        req.approver = request.user
        req.save()
        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@login_required
@require_POST
def apply_all_normal(request):
    try:
        data = json.loads(request.body)
        year = int(data.get('year'))
        month = int(data.get('month'))
        profile_ids = data.get('profile_ids', [])
        
        if not (request.user.is_superuser or (hasattr(request.user, 'profile') and request.user.profile.is_pl)):
             return JsonResponse({'status': 'error', 'message': '권한이 없습니다.'}, status=403)

        normal_type = WorkType.objects.filter(name__contains="정상").first()
        if not normal_type: normal_type = WorkType.objects.first()
        
        kr_holidays = holidays.KR(years=year) if holidays else {}
        _, num_days = calendar.monthrange(year, month)
        create_list = []
        
        for pid in profile_ids:
            target_profile = Profile.objects.get(pk=pid)
            if not is_my_trainee(request.user, target_profile): continue

            for day in range(1, num_days + 1):
                curr_date = date(year, month, day)
                # 주말/공휴일 제외
                if curr_date.weekday() >= 5 or curr_date in kr_holidays:
                    continue

                if not DailySchedule.objects.filter(profile_id=pid, date=curr_date).exists():
                    create_list.append(DailySchedule(profile_id=pid, date=curr_date, work_type=normal_type))
        
        DailySchedule.objects.bulk_create(create_list)
        return JsonResponse({'status': 'success', 'count': len(create_list)})
        
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)