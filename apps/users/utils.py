from django.utils import timezone
from django.db.models.functions import Coalesce
import re
from apps.incidents.models import Incident

def format_duration_human(total_m):
    """
    Converte minutos em string amigável: 'Xd Yh Zmin'
    """
    if total_m <= 0: return "0min"
    d = total_m // 1440
    h = (total_m % 1440) // 60
    m = total_m % 60
    parts = []
    if d > 0: parts.append(f"{d}d")
    if h > 0: parts.append(f"{h}h")
    parts.append(f"{m}min")
    return " ".join(parts)

def get_detailed_timeline_data(protocolo):
    incident = Incident.objects.select_related(
        'status', 'incident_type', 'site', 'circuit', 'circuit__provider', 
        'device', 'reported_symptom', 'detection_source', 'root_cause',
        'impact_type', 'impact_level', 'client_type', 'assigned_to', 'created_by'
    ).prefetch_related('updates__created_by', 'updates__status', 'updates__tags').filter(mk_protocol=protocolo).first()
    
    if not incident: return None

    now = timezone.now()
    is_concluido = incident.status.name.lower() in ['normalizado', 'resolvido', 'encerrado']
    end_time = incident.resolved_at if is_concluido else now
    if not end_time: end_time = now
    
    updates = incident.updates.annotate(
        effective_time=Coalesce('user_updated_at', 'created_at')
    ).order_by('effective_time', 'created_at')

    segments = []
    last_time = incident.occured_at
    first_update = updates.first() if updates.exists() else None
    currently_impacted = first_update.is_impact_active if first_update else incident.is_impact_active
    last_event_name = "Abertura do Chamado"
    last_author = incident.created_by.username if incident.created_by else "Sistema"
    last_comment = incident.description
    
    for update in updates:
        event_time = update.effective_time
        duration_sec = (event_time - last_time).total_seconds()
        if duration_sec < 0: duration_sec = 0
        
        segments.append({
            'de': last_time,
            'ate': event_time,
            'duracao_str': format_duration_human(int(duration_sec // 60)) if duration_sec > 0 else "Instantâneo",
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
        if duration_sec < 0: duration_sec = 0
        segments.append({
            'de': last_time,
            'ate': end_time,
            'duracao_str': format_duration_human(int(duration_sec // 60)),
            'impacto': currently_impacted,
            'evento': last_event_name,
            'autor': last_author,
            'comentario': last_comment
        })
    
    if is_concluido:
        conclusao_comment = incident.rfo if incident.rfo else last_comment
        segments.append({
            'de': end_time,
            'ate': None,
            'duracao_str': "-",
            'impacto': currently_impacted,
            'evento': f"🏁 Conclusão: {incident.status.name}",
            'autor': last_author,
            'comentario': conclusao_comment
        })
    
    # [CORREÇÃO] total_impact_min deve considerar ate - de, mas verificar se ate não é None
    total_impact_min = sum((s['ate'] - s['de']).total_seconds() // 60 for s in segments if s['impacto'] and s['ate'])
    
    sla_limit_min = 240
    if incident.sla and incident.sla.name:
        digits = re.findall(r'\d+', str(incident.sla.name))
        if digits: sla_limit_min = int(digits[0]) * 60
    
    sla_met = total_impact_min <= sla_limit_min

    return {
        'incident': incident,
        'segments': segments,
        'total_impact_str': format_duration_human(int(total_impact_min)),
        'total_decorrido_str': format_duration_human(int((end_time - incident.occured_at).total_seconds() // 60)),
        'sla_met': sla_met,
        'sla_limit_str': format_duration_human(sla_limit_min),
        'now': now
    }
