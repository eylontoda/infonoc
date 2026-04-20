from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User
from simple_history.admin import SimpleHistoryAdmin

# [NOVO] Registra o Usuário com suporte ao histórico de auditoria
@admin.register(User)
class CustomUserAdmin(UserAdmin, SimpleHistoryAdmin):
    # Adiciona seus campos extras na visualização do admin
    fieldsets = UserAdmin.fieldsets + (
        ('Informações NOC', {'fields': ('is_online', 'last_access')}),
    )
    list_display = ['username', 'email', 'is_online', 'is_staff']