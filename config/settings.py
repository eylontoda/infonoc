import os
import sys
import environ
from pathlib import Path

# [NOVO] BASE_DIR ajustado para a nova posição (config/settings.py)
BASE_DIR = Path(__file__).resolve().parent.parent

# [NOVO] Inicialização do Environ com fallbacks seguros
env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ['*']),
)

# [NOVO] Tentativa de leitura do .env na raiz
env_file = os.path.join(BASE_DIR, ".env")
if os.path.exists(env_file):
    environ.Env.read_env(env_file)

# --- 1. CONFIGURAÇÕES DE NÚCLEO ---
SECRET_KEY = env("SECRET_KEY", default='django-insecure-mude-isso-em-producao')
DEBUG = env("DEBUG") # [NOVO] Sem default para forçar definição no ambiente
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS")

# [NOVO] Ajuste de Path para as Apps
sys.path.insert(0, os.path.join(BASE_DIR, 'apps'))

# --- 2. INTEGRAÇÕES EXTERNAS (NETBOX) ---
NETBOX_API_URL = env("NETBOX_API_URL", default=None)
NETBOX_API_TOKEN = env("NETBOX_API_TOKEN", default=None)

# --- 3. DEFINIÇÃO DE APLICAÇÕES ---
DJANGO_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

THIRD_PARTY_APPS = [
    'simple_history',
    'rest_framework',
    'whitenoise.runserver_nostatic', # [NOVO] Melhora performance do static em dev
]

LOCAL_APPS = [
    'apps.users',
    'apps.core',
    'apps.incidents',
    'apps.netbox',
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# --- 4. MIDDLEWARES (ORDEM IMPORTA) ---
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware', # [NOVO] Whitenoise logo após Security
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'simple_history.middleware.HistoryRequestMiddleware',
]

# --- 5. BANCO DE DADOS ---
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'infonoc',
        'USER': 'infonoc_user',
        'PASSWORD': '11223344',
        'HOST': env("POSTGRES_HOST", default="db"), # Tenta ler do .env, senão usa 'db'[NOVO] Alterado de 'db' para localhost para execução fora do docker
        'PORT': '5432',
        'CONN_MAX_AGE': 60,
    }
}

# --- 6. TEMPLATES E URLS ---
ROOT_URLCONF = 'config.urls'
AUTH_USER_MODEL = 'users.User'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

# --- 7. INTERNACIONALIZAÇÃO ---
LANGUAGE_CODE = 'pt-br'
TIME_ZONE = 'America/Belem'
USE_I18N = True
USE_TZ = True

# --- 8. ARQUIVOS ESTÁTICOS (WHITENOISE) ---
STATIC_URL = 'static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'static')]

# [NOVO] Otimização de armazenamento WhiteNoise
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# --- 9. SEGURANÇA E AUTH ---
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
LOGIN_URL = 'users:login'
LOGIN_REDIRECT_URL = 'users:home'
LOGOUT_REDIRECT_URL = 'users:login'

PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    'apps.users.hashers.WerkzeugPasswordHasher', # Legado do SQLite
    'django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher',
    'django.contrib.auth.hashers.Argon2PasswordHasher',
]

# [NOVO] Confiança em Proxy (Essencial para Docker/Nginx)
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')