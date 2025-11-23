"""
Django settings for config project.
"""

from pathlib import Path
import os
import dj_database_url
from django.core.exceptions import ImproperlyConfigured # [필수] 환경 변수 누락 시 에러 발생용

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# ------------------------------------------------------------------------------
# [보안 핵심 1] 환경 변수 처리 헬퍼 함수
# ------------------------------------------------------------------------------
def get_env_variable(var_name, default=None):
    """환경 변수를 가져오거나, 없으면 에러를 발생시켜 서버 시작을 막습니다."""
    try:
        return os.environ[var_name]
    except KeyError:
        if default is not None:
            return default
        error_msg = f"CRITICAL ERROR: The {var_name} environment variable is not set."
        raise ImproperlyConfigured(error_msg)

# ------------------------------------------------------------------------------
# [보안 핵심 2] SECRET_KEY & DEBUG 설정
# ------------------------------------------------------------------------------

# SECRET_KEY는 환경 변수에서 반드시 가져와야 하며, 없으면 서버가 켜지지 않습니다.
SECRET_KEY = get_env_variable('DJANGO_SECRET_KEY')

# DEBUG는 기본적으로 False입니다. 환경 변수에 'True'라고 명시해야만 켜집니다.
# DEBUG = os.environ.get('DJANGO_DEBUG', 'False') == 'True'
DEBUG = True
# ALLOWED_HOSTS: DEBUG가 꺼져있을 때는 반드시 도메인을 제한합니다.
ALLOWED_HOSTS = []
if not DEBUG:
    # 배포 환경 (Render 등)
    ALLOWED_HOSTS = ['.onrender.com', 'localhost', '127.0.0.1']
else:
    # 로컬 개발 환경
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

    'storages', 
]

# 개발 모드일 때만 WhiteNoise 실행
if DEBUG:
    INSTALLED_APPS.append('whitenoise.runserver_nostatic')


MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware', 
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    
    # [커스텀 보안 미들웨어]
    'accounts.middleware.ForcePasswordChangeMiddleware',
    'accounts.middleware.AccountStatusMiddleware',
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
# 로컬은 sqlite3, 배포(Render)는 DATABASE_URL(PostgreSQL) 자동 감지
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
USE_I18N = True
USE_TZ = True


# ------------------------------------------------------------------------------
# Static & Media Files (배포/로컬 자동 분기)
# ------------------------------------------------------------------------------
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

if not DEBUG:
    # [배포 환경]
    STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
    STATICFILES_DIRS = []
    
    # Cloudflare R2 (S3 호환) 스토리지 설정
    DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'
    
    AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY')
    AWS_STORAGE_BUCKET_NAME = os.environ.get('AWS_STORAGE_BUCKET_NAME')
    AWS_S3_ENDPOINT_URL = os.environ.get('AWS_S3_ENDPOINT_URL')
    AWS_S3_REGION_NAME = 'auto'
    AWS_S3_SIGNATURE_VERSION = 's3v4'
    AWS_DEFAULT_ACL = None
    
    MEDIA_URL = f'{AWS_S3_ENDPOINT_URL}/{AWS_STORAGE_BUCKET_NAME}/media/'

    # [보안 핵심 3] 배포 시 보안 헤더 강화 (HTTPS 강제)
    SECURE_SSL_REDIRECT = True          # 모든 HTTP 요청을 HTTPS로 리다이렉트
    SESSION_COOKIE_SECURE = True        # 쿠키도 HTTPS에서만 전송
    CSRF_COOKIE_SECURE = True           # CSRF 토큰도 HTTPS에서만 전송
    SECURE_BROWSER_XSS_FILTER = True    # XSS 필터 활성화
    SECURE_CONTENT_TYPE_NOSNIFF = True  # MIME 타입 스니핑 방지

else:
    # [로컬 개발 환경]
    STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'
    STATICFILES_DIRS = [BASE_DIR / 'static',]
    
    DEFAULT_FILE_STORAGE = 'django.core.files.storage.FileSystemStorage'
    MEDIA_URL = '/media/'
    MEDIA_ROOT = BASE_DIR / 'media'


# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# --- 핵심 기능 설정 ---
LOGIN_REDIRECT_URL = '/quiz/mypage/'
LOGOUT_REDIRECT_URL = '/accounts/login/'

# ASGI & Channels
ASGI_APPLICATION = 'config.asgi.application'
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer"
    }
}

# Session (보안: 브라우저 닫으면 로그아웃되게 하려면 False, 유지하려면 True)
SESSION_COOKIE_AGE = 10800 # 3시간
SESSION_SAVE_EVERY_REQUEST = True

# Admin Interface
ADMIN_INTERFACE_SETTINGS = {
    'TITLE': 'PMTC CBT 관리 사이트', 
    'SHOW_HEADER': True,
    'SHOW_SIDEMENU': True,
}

ADMIN_INTERFACE_MODELS_GROUP_BY_CATEGORY = [
    {
        "name": "1. 교육 운영 관리",
        "models": [
            "accounts.Cohort",
            "accounts.Profile",
            "quiz.QuizAttempt",
            "quiz.TestResult",
        ],
    },
    {
        "name": "2. 매니저 평가 시스템",
        "models": [
            "accounts.ManagerEvaluation",
            "accounts.EvaluationCategory",
            "accounts.EvaluationItem",
            "accounts.EvaluationRecord",
        ],
    },
    {
        "name": "3. 퀴즈 콘텐츠 관리",
        "models": [
            "quiz.Quiz",
            "quiz.ExamSheet",
            "quiz.Question",
            "quiz.Tag",
        ],
    },
    {
        "name": "4. 기준 정보 설정",
        "models": [
            "accounts.Company",
            "accounts.Process",
            "accounts.PartLeader",
            "accounts.Badge",
            "accounts.RecordType",
        ],
    },
    {
        "name": "5. 시스템 및 로그",
        "models": [
            "auth.User",
            "auth.Group",
            "sites.Site",
            "admin_interface.Theme",
            "quiz.UserAnswer",
            "quiz.Choice",
        ],
    },
]

# Django Sites
SITE_ID = 1

# [실제 배포/테스트용 SMTP 설정]
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True

# 환경 변수에서 가져오기 (없으면 None, 에러는 안 남)
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD')