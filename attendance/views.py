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
# [Helper] 권한 검증 함수
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
# 1. MDM 인증 (기존 유지)
# ------------------------------------------------------------------
@login_required
def upload_mdm(request):
    today = timezone.now().date()
    schedule = DailySchedule.objects.filter(profile=request.user.profile, date=today).first()

    if request.method == 'POST' and request.FILES.get('mdm_image'):
        image_file = request.FILES['mdm_image']
        
        if not schedule:
            default_work = WorkType.objects.filter(name__contains="정상").first()
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
# 2. 캘린더 스케줄 조회 (관리자/매니저: 2번 방식 + 교육생: 팀/본인 옵션)
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
    weekday_map = {0: '월', 1: '화', 2: '수', 3: '목', 4: '금', 5: '토', 6: '일'}

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

    # [공통] 이름이 있는 모든 프로필을 기본 베이스로
    profiles = Profile.objects.select_related('cohort', 'process') \
                              .exclude(name__isnull=True) \
                              .exclude(name='')

    # 관리자/매니저 여부
    is_manager_or_admin = user.is_superuser or (
        hasattr(user, 'profile') and (user.profile.is_manager or user.profile.is_pl)
    )

    # 공통 GET 파라미터
    sel_role = request.GET.get('role', 'student')
    sel_cohort = request.GET.get('cohort', '')
    sel_process = request.GET.get('process', '')

    # 교육생 전용: 팀/본인 보기 옵션
    # - 관리자/매니저가 아니면 기본 'team'
    view_scope = request.GET.get('view', 'team' if not is_manager_or_admin else '')

    if is_manager_or_admin:
        # -------------------------------
        # 관리자/매니저 화면 (2번 방식 유지)
        # -------------------------------
        if sel_role == 'manager':
            # 매니저 / PL / superuser / staff 모두 포함
            profiles = profiles.filter(
                Q(is_manager=True) |
                Q(is_pl=True) |
                Q(user__is_superuser=True) |
                Q(user__is_staff=True)
            )
        else:
            # 교육생 보기 선택 시: 재직 중(attending) + 순수 교육생
            profiles = profiles.filter(
                status='attending',
                is_manager=False,
                is_pl=False,
                user__is_superuser=False,
                user__is_staff=False
            )

        if sel_cohort:
            profiles = profiles.filter(cohort_id=sel_cohort)
        if sel_process:
            profiles = profiles.filter(process_id=sel_process)

    else:
        # -------------------------------
        # 일반 교육생 화면
        #   - view=team  : 같은 공정 재직 중 교육생 전체
        #   - view=self  : 본인만
        # -------------------------------
        sel_role = 'student'  # 교육생은 role 고정

        if hasattr(user, 'profile'):
            base_qs = profiles.filter(
                status='attending',
                is_manager=False,
                is_pl=False,
                user__is_superuser=False,
                user__is_staff=False
            )

            if view_scope == 'self':
                # 내 것만
                profiles = base_qs.filter(user=user)
            else:
                # 팀 전체 보기(같은 공정) - 공정 없으면 자기만
                if user.profile.process:
                    profiles = base_qs.filter(process=user.profile.process)
                else:
                    profiles = base_qs.filter(user=user)
        else:
            profiles = profiles.none()

    profiles = profiles.order_by('name')

    # -------------------------------
    # 연차/스케줄 계산 (기존 로직 유지)
    # -------------------------------
    TOTAL_ANNUAL_LEAVE = 15
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
            if s.profile_id not in db_data:
                db_data[s.profile_id] = {}
            db_data[s.profile_id][s.date.strftime('%Y-%m-%d')] = s.work_type

    for p in profiles:
        used = leave_usage_map.get(p.id, 0)
        remain = TOTAL_ANNUAL_LEAVE - used

        row_data = {
            'profile': p,
            'daily_data': {},
            'stats': {
                'work': 0, 'rest': 0, 'leave': 0, 'half': 0, 'etc': 0,
                'annual_remain': remain,
                'annual_total': TOTAL_ANNUAL_LEAVE
            }
        }
        user_schedules = db_data.get(p.id, {})

        for day_info in days_in_month:
            d_str = day_info['date_str']
            if d_str in user_schedules:
                wt = user_schedules[d_str]
                row_data['daily_data'][d_str] = wt
                if wt.deduction == 1.0:
                    row_data['stats']['leave'] += 1
                elif 0 < wt.deduction < 1.0:
                    row_data['stats']['half'] += 1
                elif wt.is_working_day and wt.deduction == 0:
                    row_data['stats']['work'] += 1
                else:
                    if not wt.is_working_day:
                        row_data['stats']['rest'] += 1
                    else:
                        row_data['stats']['etc'] += 1
            else:
                if day_info['is_weekend'] or day_info['is_holiday']:
                    row_data['daily_data'][d_str] = None
                    row_data['stats']['rest'] += 1
                else:
                    row_data['daily_data'][d_str] = 'DEFAULT_F'
                    row_data['stats']['work'] += 1

        schedule_map[p.id] = row_data

    if today.month == 12:
        next_month_start = date(today.year + 1, 1, 1)
    else:
        next_month_start = date(today.year, today.month + 1, 1)

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
        'view_scope': view_scope,  # ★ 교육생 팀/본인 보기용
        'prev_month': (start_date - timedelta(days=1)).strftime('%Y-%m'),
        'next_month': (end_date + timedelta(days=1)).strftime('%Y-%m'),
        'is_manager': is_manager_or_admin,
    }
    return render(request, 'attendance/schedule.html', context)


# ------------------------------------------------------------------
# [핵심 수정] 3. 스케줄 수정 로직 (매니저 본인 수정 시 승인 요청)
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
        
        # 권한 기초 확인 (본인 or 관리자 or 매니저)
        is_owner = (target_profile.user == request.user)
        is_superuser = request.user.is_superuser
        
        # is_manager_of_target: 내가 이 학생의 담당 매니저인가? (본인 제외)
        is_manager_of_target = False
        if hasattr(request.user, 'profile') and request.user.profile.is_manager:
            if request.user.profile.process == target_profile.process:
                is_manager_of_target = True

        if not (is_owner or is_superuser or is_manager_of_target):
            return JsonResponse({'status': 'error', 'message': '수정 권한이 없습니다.'}, status=403)
        
        today = timezone.now().date()
        if today.month == 12:
            next_month_start = date(today.year + 1, 1, 1)
        else:
            next_month_start = date(today.year, today.month + 1, 1)

        # ----------------------------------------------
        # [권한별 분기 로직]
        # ----------------------------------------------
        
        # Case A: 과거 (~ 어제)
        if target_date < today:
            if is_superuser:
                DailySchedule.objects.update_or_create(
                    profile=target_profile, date=target_date, defaults={'work_type': work_type}
                )
                return JsonResponse({'status': 'success', 'message': '관리자 권한으로 과거 수정됨'})
            else:
                return JsonResponse({'status': 'error', 'message': '지난 날짜는 관리자만 수정 가능합니다.'})

        # Case B: 미래 (다음 달 ~ )
        elif target_date >= next_month_start:
            DailySchedule.objects.update_or_create(
                profile=target_profile, date=target_date, defaults={'work_type': work_type}
            )
            return JsonResponse({'status': 'success', 'message': '미래 근무 수정됨'})

        # Case C: 당월 (오늘 ~ 말일)
        else:
            # 1. 슈퍼유저는 프리패스
            if is_superuser:
                DailySchedule.objects.update_or_create(
                    profile=target_profile, date=target_date, defaults={'work_type': work_type}
                )
                return JsonResponse({'status': 'success', 'message': '관리자 권한 수정'})

            # 2. 매니저가 '교육생'을 수정할 때 (본인 아님) -> 프리패스
            if is_manager_of_target and not is_owner:
                DailySchedule.objects.update_or_create(
                    profile=target_profile, date=target_date, defaults={'work_type': work_type}
                )
                return JsonResponse({'status': 'success', 'message': '매니저 권한 수정'})

            # 3. 그 외 (교육생 본인 수정 OR 매니저 본인 수정) -> 승인 요청
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
    """결재 대기 목록 조회"""
    # 1. 슈퍼유저: 모든 요청 조회
    if request.user.is_superuser:
        requests = ScheduleRequest.objects.filter(status='pending')

    # 2. 매니저: '내 공정' 학생들의 요청만 조회 (단, 자기 자신이 보낸 요청은 제외)
    elif hasattr(request.user, 'profile') and request.user.profile.is_manager:
        my_process = request.user.profile.process
        requests = ScheduleRequest.objects.filter(
            requester__process=my_process, 
            status='pending'
        ).exclude(requester=request.user.profile)  # 내 요청은 내가 결재 못함
        
    else:
        # 권한 없으면 빈 리스트
        return JsonResponse({'requests': []})
        
    requests = requests.select_related('requester', 'target_work_type').order_by('date')
    
    data = [{
        'id': r.id,
        'name': r.requester.name,
        'date': r.date.strftime('%Y-%m-%d'),
        'type': r.target_work_type.short_name,
        'reason': r.reason
    } for r in requests]
    
    return JsonResponse({'requests': data})


@login_required
@require_POST
def process_request(request):
    """결재 승인/거절 처리"""
    try:
        data = json.loads(request.body)
        req = get_object_or_404(ScheduleRequest, pk=data.get('request_id'))
        
        # 권한 확인: 슈퍼유저거나 담당 매니저 (본인 요청 승인 불가 로직은 get_pending_requests에서 처리됨)
        can_approve = False
        if request.user.is_superuser:
            can_approve = True
        elif hasattr(request.user, 'profile') and request.user.profile.is_manager:
            if request.user.profile.process == req.requester.process:
                can_approve = True
        
        if not can_approve:
            return JsonResponse({'status': 'error', 'message': '권한이 없습니다.'}, status=403)

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
    """평일 일괄 적용"""
    try:
        data = json.loads(request.body)
        year = int(data.get('year'))
        month = int(data.get('month'))
        profile_ids = data.get('profile_ids', [])
        
        # 관리자/매니저만 가능
        if not (request.user.is_superuser or (hasattr(request.user, 'profile') and request.user.profile.is_manager)):
            return JsonResponse({'status': 'error', 'message': '권한이 없습니다.'}, status=403)

        normal_type = WorkType.objects.filter(name__contains="정상").first()
        if not normal_type:
            normal_type = WorkType.objects.first()
        
        kr_holidays = holidays.KR(years=year) if holidays else {}
        _, num_days = calendar.monthrange(year, month)
        create_list = []
        
        # 매니저는 본인 공정만 처리 가능
        my_process = request.user.profile.process if hasattr(request.user, 'profile') else None
        
        for pid in profile_ids:
            target_profile = Profile.objects.get(pk=pid)
            
            # 권한 체크: 슈퍼유저는 통과, 매니저는 공정 일치해야 통과
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
