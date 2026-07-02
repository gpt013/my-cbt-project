#!/usr/bin/env python3
"""
보안 수정 자동 적용 스크립트
코드스페이스 터미널에서 실행: python3 apply_security_fixes.py
"""
import re, os, sys

BASE = os.path.dirname(os.path.abspath(__file__))

def patch(path, old, new, count=1):
    full = os.path.join(BASE, path)
    with open(full, encoding='utf-8') as f:
        content = f.read()
    if old not in content:
        print(f"  ⚠️  패턴 없음 (이미 적용됐거나 파일이 다름): {path}")
        return False
    content = content.replace(old, new, count)
    with open(full, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"  ✅ 적용 완료: {path}")
    return True

def overwrite(path, content):
    full = os.path.join(BASE, path)
    with open(full, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"  ✅ 덮어쓰기 완료: {path}")

print("\n=== 보안 수정 스크립트 시작 ===\n")

# ─────────────────────────────────────────
# 1. .gitignore
# ─────────────────────────────────────────
print("[1/5] .gitignore — 민감 파일 패턴 추가")
overwrite('.gitignore', """# Django
*.log
*.pot
*.pyc
__pycache__/
local_settings.py
db.sqlite3
db.sqlite3-journal
db.sqlite3.bak
media/

# 데이터 덤프 / 백업 파일 (민감 정보 포함 가능)
data.json
*.bak
*.dump
*.sql

# Environment / Secrets
.env
.env.*
venv/
.virtualenv/

# OS / Editor
.DS_Store
.vscode/
""")

# ─────────────────────────────────────────
# 2. config/settings.py — SECRET_KEY, DEBUG, ALLOWED_HOSTS, 쿠키 보안
# ─────────────────────────────────────────
print("[2/5] config/settings.py — SECRET_KEY/DEBUG/ALLOWED_HOSTS/쿠키 보안")

# 2-a: SECRET_KEY + DEBUG + ALLOWED_HOSTS
patch('config/settings.py',
    "# [보안] Render 환경변수에 SECRET_KEY가 있으면 그걸 쓰고, 없으면 개발용 키 사용\n"
    "SECRET_KEY = os.environ.get('SECRET_KEY', 'django-insecure-dev-key-for-testing-only-do-not-use-in-production')\n"
    "\n"
    "# [보안] Render에서는 DEBUG를 False로 하는 것이 원칙이지만, \n"
    "# 에러 확인을 위해 당분간 True로 두시거나, 환경변수로 제어하세요.\n"
    "# (현재는 요청하신 대로 True 유지)\n"
    "DEBUG = True\n"
    "\n"
    "ALLOWED_HOSTS = ['*']",
    "# 환경변수에 SECRET_KEY가 없으면 명시적으로 오류 발생 (하드코딩 방지)\n"
    "_secret_key = os.environ.get('SECRET_KEY')\n"
    "if not _secret_key:\n"
    "    import sys\n"
    "    if 'runserver' in sys.argv or 'gunicorn' in ' '.join(sys.argv) or os.environ.get('DATABASE_URL'):\n"
    "        raise RuntimeError(\n"
    "            \"SECRET_KEY 환경변수가 설정되지 않았습니다. \"\n"
    "            \"프로덕션 서버 실행 전 반드시 설정해주세요.\"\n"
    "        )\n"
    "    _secret_key = 'local-dev-only-do-not-use-in-production-' + os.urandom(16).hex()\n"
    "SECRET_KEY = _secret_key\n"
    "\n"
    "# 환경변수로 DEBUG 제어 (기본값 False — 프로덕션 안전)\n"
    "DEBUG = os.environ.get('DEBUG', 'False').lower() in ('true', '1', 'yes')\n"
    "\n"
    "# 와일드카드 허용 금지: 환경변수로 명시적으로 지정\n"
    "_allowed_hosts = os.environ.get('ALLOWED_HOSTS', '')\n"
    "if _allowed_hosts:\n"
    "    ALLOWED_HOSTS = [h.strip() for h in _allowed_hosts.split(',') if h.strip()]\n"
    "else:\n"
    "    # 환경변수 미설정 시 로컬 개발용으로만 허용\n"
    "    ALLOWED_HOSTS = ['127.0.0.1', 'localhost', '.github.dev', '.app.github.dev']"
)

# 2-b: SameSite 쿠키 + HttpOnly
patch('config/settings.py',
    "CSRF_COOKIE_SAMESITE = 'None' if IS_PRODUCTION else 'Lax'\n"
    "SESSION_COOKIE_SAMESITE = 'None' if IS_PRODUCTION else 'Lax'",
    "# SameSite=None은 CSRF 방어를 약화시키므로 'Lax' 사용\n"
    "CSRF_COOKIE_SAMESITE = 'Lax'\n"
    "SESSION_COOKIE_SAMESITE = 'Lax'\n"
    "# 세션 쿠키에 HttpOnly 플래그 강제 (JS 접근 차단)\n"
    "SESSION_COOKIE_HTTPONLY = True\n"
    "CSRF_COOKIE_HTTPONLY = True"
)

# ─────────────────────────────────────────
# 3. accounts/views.py — 브루트포스 방어
# ─────────────────────────────────────────
print("[3/5] accounts/views.py — 브루트포스 방어 + 오류 메시지 보안")

# 3-a: cache import 추가
patch('accounts/views.py',
    "from django.contrib.auth import login as auth_login\n",
    "from django.contrib.auth import login as auth_login\nfrom django.core.cache import cache\n"
)

# 3-b: print 오류 → logging
patch('accounts/views.py',
    '        print(f"❌ AJAX Error: {e}")\n',
    '        import logging\n        logging.getLogger(__name__).error("AJAX load_part_leaders error: %s", e, exc_info=True)\n'
)

# 3-c: custom_login 앞에 브루트포스 상수 + 헬퍼 함수 삽입
patch('accounts/views.py',
    "def custom_login(request):\n    \"\"\"\n    [커스텀 로그인 - 최종 완성]",
    "_LOGIN_MAX_ATTEMPTS = 5       # 최대 실패 횟수\n"
    "_LOGIN_LOCKOUT_SECONDS = 300 # 잠금 시간 5분\n"
    "\n"
    "def _get_login_cache_key(request):\n"
    "    ip = request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR', 'unknown'))\n"
    "    ip = ip.split(',')[0].strip()\n"
    "    return f'login_attempts_{ip}'\n"
    "\n"
    "def custom_login(request):\n"
    "    \"\"\"\n"
    "    [커스텀 로그인 - 최종 완성]"
)

# 3-d: 브루트포스 체크 + 성공 시 카운터 초기화 + 실패 시 카운터 증가
patch('accounts/views.py',
    '    """\n    if request.method == \'POST\':\n        form = AuthenticationForm(request, data=request.POST)\n        \n        if form.is_valid():\n            user = form.get_user()\n            \n            try:\n                # 프로필 가져오기',
    '    """\n'
    '    # 브루트포스 방어: IP별 로그인 실패 횟수 제한\n'
    '    cache_key = _get_login_cache_key(request)\n'
    '    attempts = cache.get(cache_key, 0)\n'
    '    if attempts >= _LOGIN_MAX_ATTEMPTS:\n'
    '        messages.error(request, f"⛔ 로그인 시도가 너무 많습니다. {_LOGIN_LOCKOUT_SECONDS // 60}분 후 다시 시도해주세요.")\n'
    '        return render(request, \'accounts/login.html\', {\'form\': AuthenticationForm()})\n'
    '\n'
    '    if request.method == \'POST\':\n'
    '        form = AuthenticationForm(request, data=request.POST)\n'
    '\n'
    '        if form.is_valid():\n'
    '            user = form.get_user()\n'
    '\n'
    '            try:\n'
    '                # 로그인 성공 시 실패 카운터 초기화\n'
    '                cache.delete(cache_key)\n'
    '\n'
    '                # 프로필 가져오기'
)

# 3-e: 로그인 실패 시 카운터 증가 + 남은 횟수 표시
patch('accounts/views.py',
    '        else:\n            # 아이디/비번 틀림\n            return render(request, \'accounts/login.html\', {\'form\': form})',
    '        else:\n'
    '            # 아이디/비번 틀림 → 실패 횟수 증가\n'
    '            cache.set(cache_key, attempts + 1, _LOGIN_LOCKOUT_SECONDS)\n'
    '            remaining = _LOGIN_MAX_ATTEMPTS - (attempts + 1)\n'
    '            if remaining > 0:\n'
    '                messages.warning(request, f"아이디 또는 비밀번호가 틀렸습니다. (남은 시도: {remaining}회)")\n'
    '            return render(request, \'accounts/login.html\', {\'form\': form})'
)

# 3-f: Login 예외에서 print → logging
patch('accounts/views.py',
    '            except Exception as e:\n                print(f"Login Logic Error: {e}")\n                messages.error(request, "로그인 처리 중 오류가 발생했습니다.")',
    '            except Exception as e:\n'
    '                import logging\n'
    '                logging.getLogger(__name__).error("Login Logic Error: %s", e, exc_info=True)\n'
    '                messages.error(request, "로그인 처리 중 오류가 발생했습니다.")'
)

# ─────────────────────────────────────────
# 4. quiz/consumers.py — WebSocket 인증
# ─────────────────────────────────────────
print("[4/5] quiz/consumers.py — WebSocket 인증 및 참가자 검증")

patch('quiz/consumers.py',
    "class ChatConsumer(AsyncWebsocketConsumer):\n    async def connect(self):\n        self.room_id = self.scope['url_route']['kwargs']['room_id']\n        self.room_group_name = f'chat_{self.room_id}'\n\n        await self.channel_layer.group_add(self.room_group_name, self.channel_name)\n        await self.accept()\n\n    async def disconnect(self, close_code):\n        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)\n\n    async def receive(self, text_data):\n        text_data_json",
    "class ChatConsumer(AsyncWebsocketConsumer):\n"
    "    async def connect(self):\n"
    "        # 인증된 사용자만 연결 허용\n"
    "        if not self.scope['user'].is_authenticated:\n"
    "            await self.close()\n"
    "            return\n"
    "\n"
    "        self.room_id = self.scope['url_route']['kwargs']['room_id']\n"
    "        self.room_group_name = f'chat_{self.room_id}'\n"
    "\n"
    "        # 해당 채팅방 참가자인지 확인 (IDOR 방지)\n"
    "        is_participant = await self.check_room_participant()\n"
    "        if not is_participant:\n"
    "            await self.close()\n"
    "            return\n"
    "\n"
    "        self.user = self.scope['user']\n"
    "        await self.channel_layer.group_add(self.room_group_name, self.channel_name)\n"
    "        await self.accept()\n"
    "\n"
    "    @database_sync_to_async\n"
    "    def check_room_participant(self):\n"
    "        user = self.scope['user']\n"
    "        try:\n"
    "            room = ChatRoom.objects.get(id=self.room_id)\n"
    "            return room.participants.filter(id=user.id).exists() or user.is_superuser\n"
    "        except ChatRoom.DoesNotExist:\n"
    "            return False\n"
    "\n"
    "    async def disconnect(self, close_code):\n"
    "        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)\n"
    "\n"
    "    async def receive(self, text_data):\n"
    "        # 인증 재확인 (연결 후 세션 만료 방지)\n"
    "        if not self.scope['user'].is_authenticated:\n"
    "            await self.close()\n"
    "            return\n"
    "\n"
    "        text_data_json"
)

# ─────────────────────────────────────────
# 5. quiz/views.py — 파일 업로드 + IDOR 수정
# ─────────────────────────────────────────
print("[5/5] quiz/views.py — 파일 업로드 보안 + IDOR 접근제어")

# 5-a: upload_quiz — 확장자/크기 검증 추가
patch('quiz/views.py',
    "    if request.method == 'POST':\n        try:\n            excel_file = request.FILES.get('excel_file')\n            if not excel_file:\n                messages.error(request, \"파일을 선택해주세요.\")\n                return redirect('quiz:upload_quiz')\n\n            df = pd.read_excel(excel_file).fillna('')",
    "    if request.method == 'POST':\n"
    "        try:\n"
    "            excel_file = request.FILES.get('excel_file')\n"
    "            if not excel_file:\n"
    "                messages.error(request, \"파일을 선택해주세요.\")\n"
    "                return redirect('quiz:upload_quiz')\n"
    "\n"
    "            # 엑셀 파일 확장자 및 크기 검증\n"
    "            _allowed_excel_ext = {'.xlsx', '.xls'}\n"
    "            _max_excel_size = 5 * 1024 * 1024  # 5MB\n"
    "            import os as _os_upload\n"
    "            _, _ext = _os_upload.path.splitext(excel_file.name.lower())\n"
    "            if _ext not in _allowed_excel_ext:\n"
    "                messages.error(request, \"xlsx 또는 xls 파일만 업로드 가능합니다.\")\n"
    "                return redirect('quiz:upload_quiz')\n"
    "            if excel_file.size > _max_excel_size:\n"
    "                messages.error(request, \"파일 크기는 5MB를 초과할 수 없습니다.\")\n"
    "                return redirect('quiz:upload_quiz')\n"
    "\n"
    "            df = pd.read_excel(excel_file).fillna('')"
)

# 5-b: chat_file_upload — csrf_exempt 제거 및 보안 강화
# @csrf_exempt 데코레이터 제거
patch('quiz/views.py',
    "@csrf_exempt\ndef chat_file_upload(request):\n    if request.method != 'POST':\n        return JsonResponse({'status': 'error', 'message': '잘못된 요청'}, status=405)\n    if not request.user.is_authenticated:\n        return JsonResponse({'status': 'error', 'message': '로그인이 필요합니다.'}, status=401)\n\n    uploaded_file = request.FILES.get('file')\n    if not uploaded_file:\n        return JsonResponse({'status': 'error', 'message': '파일이 없습니다.'}, status=400)\n\n    fs = FileSystemStorage()\n    filename = fs.save(f\"chat_files/{uploaded_file.name}\", uploaded_file)\n    file_url = fs.url(filename)\n\n    return JsonResponse({\n        'status': 'success',\n        'file_url': file_url,\n        'file_name': uploaded_file.name,\n    })",
    "import os as _os\n\n"
    "# 허용 확장자 화이트리스트 (실행 가능한 파일 차단)\n"
    "_ALLOWED_CHAT_EXTENSIONS = {\n"
    "    '.jpg', '.jpeg', '.png', '.gif', '.webp',\n"
    "    '.pdf', '.txt', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',\n"
    "    '.zip', '.mp4', '.mp3',\n"
    "}\n"
    "_MAX_CHAT_FILE_SIZE = 10 * 1024 * 1024  # 10MB\n"
    "\n"
    "@login_required\n"
    "@require_POST\n"
    "def chat_file_upload(request):\n"
    "    uploaded_file = request.FILES.get('file')\n"
    "    if not uploaded_file:\n"
    "        return JsonResponse({'status': 'error', 'message': '파일이 없습니다.'}, status=400)\n"
    "\n"
    "    # 파일 크기 제한\n"
    "    if uploaded_file.size > _MAX_CHAT_FILE_SIZE:\n"
    "        return JsonResponse({'status': 'error', 'message': '파일 크기는 10MB를 초과할 수 없습니다.'}, status=400)\n"
    "\n"
    "    # 확장자 화이트리스트 검증\n"
    "    _, ext = _os.path.splitext(uploaded_file.name.lower())\n"
    "    if ext not in _ALLOWED_CHAT_EXTENSIONS:\n"
    "        return JsonResponse({'status': 'error', 'message': '허용되지 않는 파일 형식입니다.'}, status=400)\n"
    "\n"
    "    # 파일명에서 경로 구분자 제거 (path traversal 방지)\n"
    "    safe_name = _os.path.basename(uploaded_file.name)\n"
    "\n"
    "    fs = FileSystemStorage()\n"
    "    filename = fs.save(f\"chat_files/{safe_name}\", uploaded_file)\n"
    "    file_url = fs.url(filename)\n"
    "\n"
    "    return JsonResponse({\n"
    "        'status': 'success',\n"
    "        'file_url': file_url,\n"
    "        'file_name': safe_name,\n"
    "    })"
)

# 5-c: manager_trainee_report IDOR
patch('quiz/views.py',
    "def manager_trainee_report(request, profile_id):\n    profile = get_object_or_404(Profile, pk=profile_id)\n\n    # 1. 통계 데이터 계산",
    "def manager_trainee_report(request, profile_id):\n"
    "    profile = get_object_or_404(Profile, pk=profile_id)\n"
    "\n"
    "    # [보안] 관리자/담당 공정 매니저만 접근 가능 (IDOR 방지)\n"
    "    if not request.user.is_staff and not is_process_manager(request.user, profile):\n"
    "        messages.error(request, \"접근 권한이 없습니다.\")\n"
    "        return redirect('quiz:index')\n"
    "\n"
    "    # 1. 통계 데이터 계산"
)

# 5-d: final_log_saver IDOR
patch('quiz/views.py',
    "def final_log_saver(request, profile_id):\n    try:\n        profile = get_object_or_404(Profile, pk=profile_id)\n\n        # 데이터 수신",
    "def final_log_saver(request, profile_id):\n"
    "    try:\n"
    "        profile = get_object_or_404(Profile, pk=profile_id)\n"
    "\n"
    "        # [보안] 관리자/담당 공정 매니저만 평가 로그 작성 가능 (쓰기 IDOR 방지)\n"
    "        if not request.user.is_staff and not is_process_manager(request.user, profile):\n"
    "            return JsonResponse({'status': 'error', 'message': '권한이 없습니다.'}, status=403)\n"
    "\n"
    "        # 데이터 수신"
)

# 5-e: student_log_create IDOR
patch('quiz/views.py',
    "    if request.method == 'POST':\n        student = get_object_or_404(User, pk=student_id) # 또는 Profile 모델\n        profile = getattr(student, 'profile', None)\n\n        # 폼 데이터 가져오기",
    "    if request.method == 'POST':\n"
    "        student = get_object_or_404(User, pk=student_id)\n"
    "        profile = getattr(student, 'profile', None)\n"
    "\n"
    "        # [보안] 관리자/담당 공정 매니저만 로그 작성 가능 (권한 상승 차단)\n"
    "        if not request.user.is_staff and not (profile and is_process_manager(request.user, profile)):\n"
    "            return JsonResponse({'status': 'error', 'message': '권한이 없습니다.'}, status=403)\n"
    "\n"
    "        # 폼 데이터 가져오기"
)

# 5-f: chat_search_messages IDOR
patch('quiz/views.py',
    "def chat_search_messages(request, room_id):\n    \"\"\"채팅방 내부 키워드 검색 API\"\"\"\n    room = get_object_or_404(ChatRoom, id=room_id)\n\n    q = request.GET.get('q', '')",
    "def chat_search_messages(request, room_id):\n"
    "    \"\"\"채팅방 내부 키워드 검색 API\"\"\"\n"
    "    room = get_object_or_404(ChatRoom, id=room_id)\n"
    "\n"
    "    # [보안] 해당 방 참가자만 대화 내용 검색 가능 (사생활 노출 방지)\n"
    "    if request.user not in room.participants.all() and not request.user.is_superuser:\n"
    "        return JsonResponse({'results': [], 'error': '권한이 없습니다.'}, status=403)\n"
    "\n"
    "    q = request.GET.get('q', '')"
)

# 5-g: chat_read_status IDOR
patch('quiz/views.py',
    "def chat_read_status(request, msg_id):\n    \"\"\"특정 메시지를 읽은 사람 / 안 읽은 사람 명단 반환\"\"\"\n    msg = get_object_or_404(ChatMessage, id=msg_id)\n    room = msg.room\n\n    read_users",
    "def chat_read_status(request, msg_id):\n"
    "    \"\"\"특정 메시지를 읽은 사람 / 안 읽은 사람 명단 반환\"\"\"\n"
    "    msg = get_object_or_404(ChatMessage, id=msg_id)\n"
    "    room = msg.room\n"
    "\n"
    "    # [보안] 해당 방 참가자만 조회 가능\n"
    "    if request.user not in room.participants.all() and not request.user.is_superuser:\n"
    "        return JsonResponse({'error': '권한이 없습니다.'}, status=403)\n"
    "\n"
    "    read_users"
)

# 5-h: chat_pin_message IDOR
patch('quiz/views.py',
    "def chat_pin_message(request, room_id):\n    \"\"\"특정 메시지를 방 상단에 공지로 고정(Pin)\"\"\"\n    room = get_object_or_404(ChatRoom, id=room_id)\n\n    msg_id = request.POST.get('msg_id')",
    "def chat_pin_message(request, room_id):\n"
    "    \"\"\"특정 메시지를 방 상단에 공지로 고정(Pin)\"\"\"\n"
    "    room = get_object_or_404(ChatRoom, id=room_id)\n"
    "\n"
    "    # [보안] 해당 방 참가자만 공지 고정/해제 가능\n"
    "    if request.user not in room.participants.all() and not request.user.is_superuser:\n"
    "        return JsonResponse({'status': 'error', 'message': '권한이 없습니다.'}, status=403)\n"
    "\n"
    "    msg_id = request.POST.get('msg_id')"
)

# 5-i: chat_invite_targets IDOR
patch('quiz/views.py',
    "def chat_invite_targets(request, room_id):\n    \"\"\"현재 채팅방 멤버를 제외한 초대 가능 인원 목록을 반환\"\"\"\n    room = get_object_or_404(ChatRoom, id=room_id)\n\n    # 1. 현재 방에 이미",
    "def chat_invite_targets(request, room_id):\n"
    "    \"\"\"현재 채팅방 멤버를 제외한 초대 가능 인원 목록을 반환\"\"\"\n"
    "    room = get_object_or_404(ChatRoom, id=room_id)\n"
    "\n"
    "    # [보안] 해당 방 참가자만 초대 대상 목록 조회 가능\n"
    "    if request.user not in room.participants.all() and not request.user.is_superuser:\n"
    "        return JsonResponse({'users': [], 'error': '권한이 없습니다.'}, status=403)\n"
    "\n"
    "    # 1. 현재 방에 이미"
)

print("\n=== 완료! 이제 다음 명령으로 커밋하세요 ===\n")
print("git add -p  # 또는  git add .")
print("git commit -m '보안 취약점 수정: SECRET_KEY/DEBUG/ALLOWED_HOSTS, 브루트포스방어, WebSocket인증, 파일업로드보안, IDOR접근제어'")
print("git push -u origin claude/github-code-security-review-t4lmn6\n")
