"""
Django settings for eco_prom project.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = 'django-insecure--td!ue(3(tj-5zzu@(f-8cv3+&gs&187m=%6cqtxy$)4zy4^yg'

DEBUG = True

ALLOWED_HOSTS = [
    '127.0.0.1',
    'localhost',
    'uniflagellate-menseless-tama.ngrok-free.dev'
]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    
    'orders',
]

# YANGI: MEDIA SOZLAMALARI
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'eco_prom.urls'

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

WSGI_APPLICATION = 'eco_prom.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

CSRF_TRUSTED_ORIGINS = [
    'https://uniflagellate-menseless-tama.ngrok-free.dev'
]

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

# =======================================================
# 💡 VAQT ZONASI SOZLAMALARI
# =======================================================
LANGUAGE_CODE = 'en-us'

USE_I18N = True

# 1. Vaqt zonasidan foydalanishni yoqish
USE_TZ = True 

# 2. Asosiy vaqt zonasini o'rnatish
TIME_ZONE = 'Asia/Tashkent' 

# =======================================================

STATIC_URL = 'static/'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# =======================================================
# 🔐 KIRISH VA YO'NALTIRISH SOZLAMALARI (Tuzatildi)
# =======================================================

# Foydalanuvchi tizimga kirishi kerak bo'lgan manzil.
LOGIN_URL = '/login/' 

# Muvaffaqiyatli kirishdan so'ng yo'naltirish manzili.
LOGIN_REDIRECT_URL = '/orders/'

# Tizimdan chiqish (logout) amali bajarilgandan so'ng /login/ sahifasiga qaytarish.
LOGOUT_REDIRECT_URL = '/login/'
