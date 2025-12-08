"""
Django settings for config project.
"""

from pathlib import Path
import os
import dj_database_url

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/

# [보안] Render 환경변수에 SECRET_KEY가 있으면 그걸 쓰고, 없으면 개발용 키 사용
SECRET_KEY = os.environ.get('SECRET_KEY', 'django-insecure-dev-key-for-testing-only-do-not-use-in-production')

# [보안] Render에서는 DEBUG를 False로 하는 것이 원칙이지만, 
# 에러 확인을 위해 당분간 True로 두시거나, 환경변수로 제어하세요.
# (현재는 요청하신 대로 True 유지)
DEBUG = True

ALLOWED_HOSTS = ['*']

# [추가] Codespaces 및 Render 환경에서 CSRF 에러 방지
CSRF_TRUSTED_ORIGINS = [
    'https://*.github.dev',
    'https://*.onrender.com',
]

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
    'attendance',

    'storages', 
    'whitenoise.runserver_nostatic', # 개발 모드에서도 정적 파일 처리
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware', 
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    
    # [기능용 미들웨어]
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
# Render 배포 시 PostgreSQL 사용, 로컬에선 SQLite 사용
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


# Static & Media Files
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# WhiteNoise를 사용하여 정적 파일 서빙
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# 미디어 파일 (S3/R2 설정이 있으면 사용, 없으면 로컬 파일시스템)
if 'AWS_ACCESS_KEY_ID' in os.environ:
    DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'
    AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY')
    AWS_STORAGE_BUCKET_NAME = os.environ.get('AWS_STORAGE_BUCKET_NAME')
    AWS_S3_ENDPOINT_URL = os.environ.get('AWS_S3_ENDPOINT_URL')
    AWS_S3_REGION_NAME = 'auto'
    AWS_S3_SIGNATURE_VERSION = 's3v4'
    AWS_DEFAULT_ACL = None
    MEDIA_URL = f'{AWS_S3_ENDPOINT_URL}/{AWS_STORAGE_BUCKET_NAME}/media/'
else:
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

# Session
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
            "accounts.StudentLog", # 추가된 로그 모델
        ],
    },
]

# Django Sites
SITE_ID = 1

# =========================================================
# [이메일 설정 수정완료] 
# (기존에 있던 console 백엔드 강제 설정을 제거했습니다)
# =========================================================
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD')
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER