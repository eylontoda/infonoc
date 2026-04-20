# config/urls.py
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    # Inclui as rotas da app users. Todas as rotas acima estarão na raiz ('')
    path('', include('apps.users.urls', namespace='users')),
]