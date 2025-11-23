"""
Django settings for config project.
"""

from pathlib import Path
import os
import dj_database_url 

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
SECRET_KEY = os.environ.get(
    'DJANGO_SECRET_KEY',
    'django-insecure-%z!i=!30c8jcpt^1uqed8y_1zduvmqho-+%%=v*811%b#%_h^w'
)

DEBUG = os.environ.get('DJANGO_DEBUG', 'True') == 'True'

ALLOWED_HOSTS = []
if not DEBUG:
    ALLOWED_HOSTS.append('.onrender.com')
else:
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
    
    # ▼▼▼ [여기를 정확히 복사해서 덮어쓰세요] ▼▼▼
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

if not DEBUG:
    STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
    STATICFILES_DIRS = []
    
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

# Session
SESSION_COOKIE_AGE = 10800
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

# 환경 변수에서 가져오기
# VS Code 등에서 설정한 변수명과 아래의 '키 값'이 정확히 일치해야 합니다.
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER')         # 보내는 사람 이메일
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD') # 앱 비밀번호 16자리

# (개발용 콘솔 설정은 주석 처리함)
# EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
# ▲▲▲ ------------------------------------------- ▲▲▲