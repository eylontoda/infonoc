import os
import django
import sys

# Ajustar o path para encontrar o módulo config
sys.path.append('/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from apps.incidents.models import Incident
from django.utils import timezone
import re

def test_extraction(protocolo):
    try:
        incident = Incident.objects.select_related(
            'status', 'incident_type', 'site', 'circuit', 'circuit__provider', 
            'device', 'reported_symptom', 'detection_source', 'root_cause',
            'impact_type', 'impact_level', 'client_type', 'assigned_to', 'created_by'
        ).prefetch_related('updates__created_by', 'updates__status', 'updates__tags').filter(mk_protocol=protocolo).first()

        if not incident:
            print(f"Protocolo {protocolo} não encontrado.")
            return

        print(f"Analisando: {incident}")
        now = timezone.now()
        end_time = incident.resolved_at or now
        
        segments = []
        last_time = incident.occured_at
        currently_impacted = True
        last_event_name = "Abertura do Chamado"
        last_author = incident.created_by.username if incident.created_by else "Sistema"
        last_comment = incident.description
        
        updates = incident.updates.all().order_by('user_updated_at', 'created_at')
        
        for update in updates:
            event_time = update.user_updated_at or update.created_at
            if event_time > last_time:
                duration_sec = (event_time - last_time).total_seconds()
                segments.append({
                    'de': last_time,
                    'ate': event_time,
                    'impacto': currently_impacted,
                    'evento': last_event_name,
                    'autor': last_author,
                    'comentario': last_comment
                })
                last_time = event_time
            
            currently_impacted = update.is_impact_active
            last_event_name = f"Atualização: {update.status.name}"
            last_author = update.created_by.username if update.created_by else "Sistema"
            last_comment = update.comment or "[Sem comentário informativo]"
            
        if end_time > last_time:
            duration_sec = (end_time - last_time).total_seconds()
            segments.append({
                'de': last_time,
                'ate': end_time,
                'impacto': currently_impacted,
                'evento': last_event_name,
                'autor': last_author,
                'comentario': last_comment
            })
        
        total_impact_min = sum((s['ate'] - s['de']).total_seconds() // 60 for s in segments if s['impacto'])
        print(f"Total Afetação: {total_impact_min} minutos")
        print("Extração concluída com sucesso no backend.")

    except Exception as e:
        import traceback
        print(f"ERRO: {str(e)}")
        print(traceback.format_exc())

if __name__ == "__main__":
    protocol = '2603.10921'
    test_extraction(protocol)
