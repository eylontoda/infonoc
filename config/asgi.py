import os
from django.core.asgi import get_asgi_application

# [NOVO] Apontando para o ficheiro único de configurações (Single Source of Truth)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

application = get_asgi_application()