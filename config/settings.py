"""
Django settings for config project.
... (주석 생략) ...
"""

from pathlib import Path
import os
import dj_database_url  # [수정] dj-database-url 임포트

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/

# [수정] Django의 비밀 키를 환경 변수에서 가져오기
SECRET_KEY = os.environ.get(
    'DJANGO_SECRET_KEY',
    'django-insecure-%z!i=!30c8jcpt^1uqed8y_1zduvmqho-+%%=v*811%b#%_h^w'
)

# [수정] DEBUG 모드를 환경 변수에서 가져오기 (로컬에서는 기본 True)
DEBUG = os.environ.get('DJANGO_DEBUG', 'True') == 'True'

# [수정] ALLOWED_HOSTS를 DEBUG 상태에 따라 동적으로 설정
ALLOWED_HOSTS = []
if not DEBUG:
    # Render의 배포 주소를 허용
    ALLOWED_HOSTS.append('.onrender.com')
else:
    # 로컬 개발 환경 허용
    ALLOWED_HOSTS = ['*']


# Application definition
INSTALLED_APPS = [
    'admin_interface',
    'colorfield',
    'channels',
    
    
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites',
    'accounts.apps.AccountsConfig',
    'quiz.apps.QuizConfig',

    # 'django_storages',  # [삭제] 잘못된 앱 이름
    'storages',  # [수정] Cloudflare R2를 위한 django-storages 앱 이름
    # 'whitenoise.runserver_nostatic', # WhiteNoise (DEBUG=True일 때만 아래에서 추가)
]

# [수정] DEBUG=True (로컬)일 때만 whitenoise.runserver_nostatic 추가
if DEBUG:
    INSTALLED_APPS.append('whitenoise.runserver_nostatic')


MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # WhiteNoise
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'accounts.middleware.ProfileCompletionMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# Database
# [수정] 로컬에서는 sqlite3, Render에서는 DATABASE_URL(PostgreSQL) 사용
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}
if 'DATABASE_URL' in os.environ:
    DATABASES['default'] = dj_database_url.parse(os.environ.get('DATABASE_URL'))


# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'ko-kr'
TIME_ZONE = 'Asia/Seoul'
USE_I18N = True  # [수정] 오타 수정 (USE_I1N → USE_I18N)
USE_TZ = True


# --- [수정] Static (정적) & Media (업로드) 파일 설정 ---
# 이 설정은 DEBUG 값에 따라 Render(배포) / Local(개발) 모드를 자동으로 전환합니다.

# 공통 설정
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'  # collectstatic으로 파일이 모일 경로

if not DEBUG:  # [Render 배포 환경일 때]

    # Static (CSS, JS)
    STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
    STATICFILES_DIRS = []  # Render에서는 필요 없음

    # Media (R2 파일 저장소)
    DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'

    # R2 연결 설정 (환경 변수에서 불러오기)
    AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY')
    AWS_STORAGE_BUCKET_NAME = os.environ.get('AWS_STORAGE_BUCKET_NAME')
    AWS_S3_ENDPOINT_URL = os.environ.get('AWS_S3_ENDPOINT_URL')

    AWS_S3_REGION_NAME = 'auto'
    AWS_S3_SIGNATURE_VERSION = 's3v4'
    AWS_DEFAULT_ACL = None

    # 업로드된 파일이 R2에서 제공될 URL
    MEDIA_URL = f'{AWS_S3_ENDPOINT_URL}/{AWS_STORAGE_BUCKET_NAME}/media/'

else:  # [로컬 개발 환경일 때]

    # Static (CSS, JS)
    STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'
    STATICFILES_DIRS = [
        BASE_DIR / 'static',
    ]

    # Media (로컬 하드디스크)
    DEFAULT_FILE_STORAGE = 'django.core.files.storage.FileSystemStorage'
    MEDIA_URL = '/media/'
    MEDIA_ROOT = BASE_DIR / 'media'

# --- 설정 끝 ---


# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# --- 핵심 기능 설정 ---
LOGIN_REDIRECT_URL = '/quiz/mypage/'
LOGOUT_REDIRECT_URL = '/accounts/login/'

# ASGI & Channels (실시간 알림)
ASGI_APPLICATION = 'config.asgi.application'
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer"
    }
}

# 자동 로그아웃 (3시간)
SESSION_COOKIE_AGE = 10800
SESSION_SAVE_EVERY_REQUEST = True

# Admin Interface (테마 및 그룹화)
ADMIN_INTERFACE_SETTINGS = {
    'TITLE': 'PMTC CBT 관리 사이트', # [수정] 여기를 변경
    'SHOW_HEADER': True,
    'SHOW_SIDEMENU': True,
}

ADMIN_INTERFACE_MODELS_GROUP_BY_CATEGORY = [
    {
        "name": "1. 교육 운영 관리",  # [가장 자주 쓰는 메뉴]
        "models": [
            "accounts.Cohort",          # 기수 (교육 차수)
            "accounts.Profile",         # 교육생 프로필
            "quiz.QuizAttempt",         # 응시 요청 (승인 처리용)
            "quiz.TestResult",          # 시험 최종 결과
        ],
    },
    {
        "name": "2. 매니저 평가 시스템", # [새로 만든 평가 기능]
        "models": [
            "accounts.ManagerEvaluation", # 매니저 최종 평가서
            "accounts.EvaluationCategory",# 평가 항목 (대분류)
            "accounts.EvaluationItem",    # 평가 예시 (체크리스트)
            "accounts.EvaluationRecord",  # (기타) 평가 기록
        ],
    },
    {
        "name": "3. 퀴즈 콘텐츠 관리",   # [문제 출제용]
        "models": [
            "quiz.Quiz",                # 퀴즈
            "quiz.ExamSheet",           # 문제 세트
            "quiz.Question",            # 문제
            "quiz.Tag",                 # 태그
        ],
    },
    {
        "name": "4. 기준 정보 설정",     # [초기 세팅용]
        "models": [
            "accounts.Company",         # 회사
            "accounts.Process",         # 공정
            "accounts.PartLeader",      # PL (파트장)
            "accounts.Badge",           # 뱃지
            "accounts.RecordType",      # 평가 기록 유형
        ],
    },
    {
        "name": "5. 시스템 및 로그",     # [잘 안 쓰는 것들]
        "models": [
            "auth.User",
            "auth.Group",
            "sites.Site",
            "admin_interface.Theme",    # 테마 설정
            "quiz.UserAnswer",          # 사용자 상세 답변 (로그성 데이터)
            "quiz.Choice",              # 보기 (문제 안에서 관리하므로 숨김 처리 추천)
        ],
    },
]

# 비밀번호 재설정 이메일 설정
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD')

# Django Sites 프레임워크
SITE_ID = 1
