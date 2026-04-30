# config/urls.py
from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.views.static import serve

urlpatterns = [
    path('admin/', admin.site.urls),
    # Inclui as rotas da app users. Todas as rotas acima estarão na raiz ('')
    path('', include('apps.users.urls', namespace='users')),
    
    # [NOVO] Rota forçada para servir MEDIA mesmo com DEBUG=False (Produção Interna)
    re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
]