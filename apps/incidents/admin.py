from django.contrib import admin
from .models import (
    Status, Incident, 
    UpdateIncident, IncidentType, RootCause, SLA
)
from simple_history.admin import SimpleHistoryAdmin

# [NOVO] Registro simples para tabelas auxiliares
admin.site.register([Status, IncidentType, RootCause, SLA])

# [NOVO] Admin robusto para Incidentes
@admin.register(Incident)
class IncidentAdmin(SimpleHistoryAdmin):
    # O que aparece na lista principal
    list_display = ('mk_protocol', 'status', 'created_at', 'assigned_to')
    
    # Filtros laterais para busca rápida
    list_filter = ('status', 'incident_type', 'created_at')
    
    # Busca por texto
    search_fields = ('mk_protocol', 'description')
    
    # Ordenação padrão
    ordering = ('-created_at',)

# [NOVO] Registro das atualizações técnicas
@admin.register(UpdateIncident)
class UpdateIncidentAdmin(SimpleHistoryAdmin):
    list_display = ('incident', 'created_by', 'status', 'created_at')