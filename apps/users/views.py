from django.shortcuts import render
from django.views.generic import TemplateView, DetailView, UpdateView
from django.contrib.auth.views import LoginView
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin, UserPassesTestMixin
from django.contrib.auth.models import Group
from django.db.models import Count, Q, F
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.core.cache import cache
from django.utils.dateparse import parse_datetime
from django.http import JsonResponse, HttpResponse
from django.urls import reverse, reverse_lazy
from asgiref.sync import sync_to_async
import traceback
import re
import json
from apps.users.utils import format_duration_human, get_detailed_timeline_data, is_third_party_incident

# Importação de todos os modelos necessários
from apps.incidents.models import (
    Incident, Status, UpdateIncident, UpdateTag, UpdateAttachment,
    ImpactType, ImpactLevel, ClientType, SLA, IncidentType,
    RootCause, Symptom, DetectionSource
)
from apps.netbox.models import Region, Site, Circuit, Device
from django.db import transaction
from django.contrib.auth import get_user_model
User = get_user_model()


class UserLoginView(LoginView):
    template_name = 'users/login.html'
    redirect_authenticated_user = True

    def form_valid(self, form):
        self.request.session['first_access_after_login'] = True
        return super().form_valid(form)

class HomeView(LoginRequiredMixin, PermissionRequiredMixin, TemplateView):
    template_name = 'users/dashboard.html'
    permission_required = 'users.acessar_dashboard'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['informativos'] = Incident.objects.exclude(
            status__name__iexact='Excluido'
        ).annotate(
            last_event=Coalesce(F('last_manual_update_at'), F('occured_at'))
        ).select_related('status', 'incident_type', 'assigned_to').order_by('-last_event')[:5]
        return context

class InformativosView(LoginRequiredMixin, PermissionRequiredMixin, TemplateView):
    template_name = 'users/informativos.html'
    permission_required = 'users.acessar_informativos'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['apply_preset'] = self.request.session.pop('first_access_after_login', False)
        return context

class RelatoriosView(LoginRequiredMixin, TemplateView):
    template_name = 'users/relatorios.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Aqui podemos injetar filtros ou dados iniciais se necessário
        return context

class IncidentDetailView(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    model = Incident
    template_name = 'users/detalhe_informativo.html'
    context_object_name = 'incident'
    permission_required = 'users.acessar_informativos'

class IncidentUpdateView(LoginRequiredMixin, PermissionRequiredMixin, UpdateView):
    model = Incident
    template_name = 'users/editar_informativo.html'
    fields = ['status', 'incident_type', 'is_impact_active', 'description']
    success_url = reverse_lazy('users:informativos')
    permission_required = 'users.editar_informativo'


# ==============================================================================
# VIEWS ASSÍNCRONAS - OFFCANVAS (HTMX)
# ==============================================================================

# --- [BOTÃO EYE] View para Visualização de Detalhes ---
async def detalhe_incidente_ajax(request, protocolo):
    try:
        user = await request.auser()
        if not user.is_authenticated:
            return HttpResponse("<div class='alert alert-warning m-3'>Sessão expirada.</div>", status=401)

        @sync_to_async
        def process_incident_data():
            # [NOVO] Adicionado impact_type no select_related para evitar query N+1
            incident = Incident.objects.select_related(
                'status', 'incident_type', 'site', 'circuit', 'circuit__provider', 
                'device', 'assigned_to', 'impact_level', 'impact_type', 'reported_symptom', 'sla'
            ).prefetch_related(
                'updates__created_by', 'updates__status', 'affected_regions'
            ).filter(Q(protocol_number=protocolo) | Q(mk_protocol=protocolo)).first()

            if not incident: return None

            now = timezone.now()
            end_time = incident.resolved_at or now

            # Cálculo de Cores da Previsão
            previsao_color = "#60c4b0"  
            if incident.expected_at:
                diff_seconds = (incident.expected_at - now).total_seconds()
                status_slug = incident.status.name.lower() if incident.status else ""
                
                # Se não estiver resolvido e o tempo passou -> Vermelho
                if not incident.resolved_at and diff_seconds < 0:
                    previsao_color = "#dc3545"  
                # Se estiver próximo de vencer (30 min) -> Amarelo
                elif not incident.resolved_at and 0 <= diff_seconds <= 1800:
                    previsao_color = "#ffc107"  

            # Cálculo de Tempos e Matemática (Mantido a iteração crescente)
            total_td = (end_time - incident.occured_at) if incident.occured_at else timezone.timedelta(0)
            impact_td = timezone.timedelta(0)
            
            updates_list = []
            if incident.occured_at:
                last_time = incident.occured_at
                currently_impacted = True 
                
                # Para matemática temporal, precisamos de ordenar ASC (Crescente)
                updates_list = sorted(list(incident.updates.all()), key=lambda u: u.created_at)
                for update in updates_list:
                    if currently_impacted and update.created_at > last_time:
                        impact_td += (update.created_at - last_time)
                    last_time = max(update.created_at, last_time)
                    currently_impacted = update.is_impact_active
                
                if currently_impacted and end_time > last_time:
                    impact_td += (end_time - last_time)

            sla_hours = 4
            has_sla = True
            if incident.sla and incident.sla.name:
                if incident.sla.name.lower() == 'sem sla':
                    has_sla = False
                    sla_hours = 0
                else:
                    digits = re.findall(r'\d+', str(incident.sla.name))
                    if digits:
                        sla_hours = int(digits[0])

            afetacao_color = "#7da233" 
            if has_sla and impact_td.total_seconds() > (sla_hours * 3600):
                afetacao_color = "#dc3545"

            def format_duration(td):
                total_m = int(td.total_seconds() // 60)
                return format_duration_human(total_m)

            # Designador e Nomes Planos
            # Designador e Nomes Planos (Sincronizado com Tabela Principal)
            tipo_nome = incident.incident_type.name if incident.incident_type else "N/D"
            if tipo_nome == 'Site' and incident.site:
                facility = incident.site.facility if incident.site.facility else incident.site.name
                circuito_nome = f"{facility} - {incident.site.name}"
            elif tipo_nome in ['Backbone', 'Core']:
                circuito_nome = incident.circuit.name if incident.circuit else "S/C"
            elif tipo_nome in ['R.A.', 'Equipamento']:
                circuito_nome = incident.device.name if incident.device else "S/D"
            else:
                circuito_nome = "N/D"
                
            # Fornecedor unificado (Tenant para Site, Provider para Circuito, Vendor para Equipamento)
            fornecedor_nome = "N/D"
            if tipo_nome in ['Backbone', 'Core'] and incident.circuit and incident.circuit.provider:
                fornecedor_nome = incident.circuit.provider.name
            elif tipo_nome == 'Site' and incident.site and incident.site.tenant:
                fornecedor_nome = incident.site.tenant.name
            elif tipo_nome in ['R.A.', 'Equipamento'] and incident.device and incident.device.vendor:
                fornecedor_nome = incident.device.vendor.name

            # [NOVO] Extracção de Impacto Físico
            impacto_tipo_nome = incident.impact_type.name if incident.impact_type else "N/D"
            impacto_nivel_nome = incident.impact_level.name if incident.impact_level else "N/D"

            # [NOVO] Histórico Otimizado com Tags M2M
            historico_updates = incident.updates.annotate(
                display_time=Coalesce(F('user_updated_at'), F('created_at'))
            ).select_related('created_by').prefetch_related('tags', 'attachments').order_by('-display_time')

            locais_list = [r.name for r in incident.affected_regions.all()]
            locais_afetados = ", ".join(locais_list) if locais_list else "Nenhum local mapeado"

            # [NOVO] Cálculo do Fim da Afetação
            fim_afetacao = None
            if not incident.is_impact_active:
                # Busca o último update que desativou o impacto
                last_impact_off = incident.updates.filter(is_impact_active=False).order_by('-user_updated_at', '-created_at').first()
                if last_impact_off:
                    fim_afetacao = last_impact_off.user_updated_at or last_impact_off.created_at

            return {
                'incident': incident,
                'is_third_party': is_third_party_incident(incident),

                'status_nome': incident.status.name if incident.status else "Desconhecido",
                'tipo_nome': tipo_nome,
                'sintoma_nome': incident.reported_symptom.name if incident.reported_symptom else "Sintoma Desconhecido",
                'circuito_nome': circuito_nome,
                'fornecedor_nome': fornecedor_nome,
                
                # Envio dos novos campos de impacto
                'impacto_tipo_nome': impacto_tipo_nome,
                'impacto_nivel_nome': impacto_nivel_nome,
                
                'locais_afetados': locais_afetados,
                'sla_nome': incident.sla.name if incident.sla else "4h",
                'tempo_total_str': format_duration(total_td),
                'tempo_afetacao_str': format_duration(impact_td),
                'previsao_color': previsao_color,
                'afetacao_color': afetacao_color,
                'historico_updates': historico_updates,
                'is_dashboard': request.GET.get('source') == 'dashboard',
                'fim_afetacao': fim_afetacao,
                'has_impact_history': impact_td.total_seconds() > 0
            }

        context_data = await process_incident_data()
        
        if not context_data:
            return HttpResponse(f"<div class='alert alert-danger m-3'>Protocolo {protocolo} não encontrado.</div>", status=404)
        
        return await sync_to_async(render)(request, 'users/partials/detalhe_offcanvas.html', context_data)

    except Exception as e:
        error_msg = f"<strong>Erro de Processamento:</strong> {str(e)}<br><small>{traceback.format_exc()}</small>"
        return HttpResponse(f"<div class='alert alert-danger m-3' style='font-size: 11px;'>{error_msg}</div>", status=200)


# --- [BOTÃO PLUS] View para Inserir Atualização Rápida ---
async def extracao_detalhada_ajax(request, protocolo):
    """
    Retorna um HTML parcial com a decomposição passo-a-passo da linha do tempo do incidente.
    """
    try:
        user = await request.auser()
        if not user.is_authenticated:
            return HttpResponse("<div class='alert alert-warning m-3'>Sessão expirada.</div>", status=401)

        data = await sync_to_async(get_detailed_timeline_data)(protocolo)
        if not data:
            return HttpResponse(f"<div class='alert alert-danger m-3'>Protocolo {protocolo} não encontrado.</div>", status=404)
            
        return await sync_to_async(render)(request, 'users/partials/relatorio_extracao.html', data)

    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(error_details)
        return HttpResponse(f"<div class='alert alert-danger m-3'><strong>Erro no Servidor:</strong> Ocorreu um problema ao gerar o relatório. Entre em contato com o suporte técnico.</div>", status=500)

async def gerar_relatorio_pdf(request, protocolo):
    """
    Gera o PDF da extração detalhada do incidente.
    """
    try:
        user = await request.auser()
        if not user.is_authenticated:
            return HttpResponse("Não autorizado", status=401)
            
        data = await sync_to_async(get_detailed_timeline_data)(protocolo)
        
        if not data:
            return HttpResponse("Protocolo não encontrado.", status=404)

        @sync_to_async
        def render_pdf(data_ctx):
            from django.template.loader import render_to_string
            from weasyprint import HTML, CSS
            
            # Render HTML template
            html_string = render_to_string('users/relatorio_pdf.html', data_ctx)
            
            # Generate PDF
            html = HTML(string=html_string, base_url=request.build_absolute_uri('/'))
            pdf = html.write_pdf()
            return pdf
            
        pdf_file = await render_pdf(data)
        
        response = HttpResponse(pdf_file, content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="Relatorio_Incidente_{protocolo}.pdf"'
        return response
        
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return HttpResponse("Erro ao gerar PDF.", status=500)

async def atualizar_incidente_ajax(request, protocolo):
    """
    Carrega o formulário (GET) com variáveis do banco ou processa o salvamento via HTMX (POST).
    """
    try:
        user = await request.auser()
        if not user.is_authenticated:
            return HttpResponse("<div class='alert alert-warning m-3'>Sessão expirada.</div>", status=401)

        # --- [POST] LÓGICA DE SALVAMENTO DE DADOS (SEM REFRESH DA PÁGINA) ---
        if request.method == 'POST':
            @sync_to_async
            def save_update():
                incident = Incident.objects.get(mk_protocol=protocolo)
                
                # Resgate de Parâmetros
                status_id = request.POST.get('status_id')
                impact_type_id = request.POST.get('impact_type_id')
                impact_level_id = request.POST.get('impact_level_id')
                # client_type e sla movidos para Edição Mestra
                
                # Novos campos
                assigned_to_id = request.POST.get('assigned_to_id')
                root_cause_id = request.POST.get('root_cause_id')
                note_text = request.POST.get('note', '').strip()
                rfo_text = request.POST.get('rfo', '').strip()
                expected_at = request.POST.get('expected_at')
                is_impact_active = request.POST.get('is_impact_active') == 'True'
                comment_text = request.POST.get('technical_note', '').strip()
                stopped_at = request.POST.get('stopped_at')
                user_updated_at_str = request.POST.get('user_updated_at')
                
                # [NOVO] Protocolo de Operadora e Anexos
                provider_protocol = request.POST.get('provider_protocol', '').strip()
                no_provider_protocol = request.POST.get('no_provider_protocol') == 'on'
                attachments_list = request.FILES.getlist('attachment')

                # Validação de Tamanho de Anexos (20MB individual)
                for att in attachments_list:
                    if att.size > 20 * 1024 * 1024:
                        response = HttpResponse(status=200)
                        response['HX-Trigger'] = json.dumps({"erroValidacao": f"O arquivo '{att.name}' é muito grande (Máx 20MB)."})
                        response['HX-Reswap'] = 'none'
                        return response
                
                new_status = Status.objects.filter(id=status_id).first()
                new_impact_level = ImpactLevel.objects.filter(id=impact_level_id).first() if impact_level_id else None
                new_impact_type = ImpactType.objects.filter(id=impact_type_id).first() if impact_type_id else None

                # [REGRA] Validação de Protocolo de Operadora no Encerramento
                if new_status and new_status.name.lower() == 'normalizado':
                    if is_third_party_incident(incident):
                        if not provider_protocol and not no_provider_protocol:
                            response = HttpResponse(status=200)
                            response['HX-Trigger'] = json.dumps({"erroValidacao": "Para chamados de terceiros, informe o Protocolo da Operadora ou marque que não houve geração."})
                            response['HX-Reswap'] = 'none'
                            return response

                # --- Lógica de Sincronização e Geração de Histórico ---
                resolved_at_str = request.POST.get('resolved_at')
                
                # Se for normalizado e houver data real de normalização, ela prevalece como horário da atualização
                if new_status and new_status.name.lower() == 'normalizado' and resolved_at_str:
                    user_updated_at_str = resolved_at_str

                now = timezone.now()
                user_updated_at = parse_datetime(user_updated_at_str) if user_updated_at_str else now
                if not user_updated_at:
                    user_updated_at = now

                if user_updated_at:
                    if timezone.is_naive(user_updated_at):
                        user_updated_at = timezone.make_aware(user_updated_at)
                    
                    if user_updated_at > now:
                        response = HttpResponse(status=200)
                        response['HX-Trigger'] = json.dumps({"erroValidacao": "A data da atualização não pode ser futura."})
                        response['HX-Reswap'] = 'none'
                        return response
                    
                    # [REGRA] Não pode ser anterior ao ÚLTIMO update registrado (para manter a coerência da timeline)
                    last_update_obj = UpdateIncident.objects.filter(incident=incident).order_by('-user_updated_at', '-created_at').first()
                    limit_time = incident.occured_at
                    if last_update_obj:
                        limit_time = last_update_obj.user_updated_at or last_update_obj.created_at
                    
                    if user_updated_at < limit_time:
                        response = HttpResponse(status=200)
                        # Ajuste de Timezone para exibição amigável
                        tz = timezone.get_current_timezone()
                        user_local = user_updated_at.astimezone(tz)
                        limit_local = limit_time.astimezone(tz)
                        
                        msg = f"Conflito: O horário informado ({user_local.strftime('%d/%m %H:%M')}) é anterior ao último registro da timeline ({limit_local.strftime('%d/%m %H:%M')})."
                        response['HX-Trigger'] = json.dumps({
                            "conflitoHorario": {
                                "message": msg,
                                "last_update_id": last_update_obj.id if last_update_obj else None,
                                "last_update_time_raw": limit_local.strftime('%Y-%m-%dT%H:%M'),
                                "protocolo": incident.mk_protocol
                            }
                        })
                        response['HX-Reswap'] = 'none'
                        return response

                detected_slugs = []
                
                # 1. Detectar Mudanças para o Histórico (Compara o que veio do POST com o estado atual do incident)
                if incident.is_impact_active != is_impact_active:
                    detected_slugs.append('impact')
                
                new_expected_at = parse_datetime(expected_at) if expected_at else None
                if new_expected_at:
                    if timezone.is_naive(new_expected_at):
                        new_expected_at = timezone.make_aware(new_expected_at)

                # [NOVAS REGRAS DE INTEGRIDADE: AFETAÇÃO VS PREVISÃO]
                if is_impact_active:
                    # 1. Com afetação: Obrigatório e Futuro
                    if not new_expected_at:
                        response = HttpResponse(status=200)
                        response['HX-Trigger'] = json.dumps({"erroValidacao": "Informe uma previsão de normalização."})
                        response['HX-Reswap'] = 'none'
                        return response
                    if new_expected_at <= now:
                        response = HttpResponse(status=200)
                        response['HX-Trigger'] = json.dumps({"erroValidacao": "A previsão deve ser uma data futura."})
                        response['HX-Reswap'] = 'none'
                        return response
                else:
                    # 2. Sem afetação: Limpa a previsão automaticamente
                    new_expected_at = None

                # Detectar Mudanças de Previsão após as regras acima
                curr_exp = incident.expected_at.replace(second=0, microsecond=0) if incident.expected_at else None
                final_exp = new_expected_at.replace(second=0, microsecond=0) if new_expected_at else None
                if curr_exp != final_exp:
                    detected_slugs.append('expected_at')

                if new_impact_level and incident.impact_level_id != new_impact_level.id:
                    detected_slugs.append('impact_level')

                if new_impact_type and incident.impact_type_id != new_impact_type.id:
                    detected_slugs.append('impact_type')

                new_stopped_at = parse_datetime(stopped_at) if stopped_at else None
                if new_stopped_at:
                    if timezone.is_naive(new_stopped_at):
                        new_stopped_at = timezone.make_aware(new_stopped_at)
                    
                    # Validação de data futura se for Pausado
                    if new_status and new_status.name.lower() == 'pausado' and new_stopped_at <= now:
                        response = HttpResponse(status=200)
                        response['HX-Trigger'] = json.dumps({"erroValidacao": "A previsão de despausa deve ser uma data futura."})
                        response['HX-Reswap'] = 'none'
                        return response

                    curr_stop = incident.stopped_at.replace(second=0, microsecond=0) if incident.stopped_at else None
                    if curr_stop != new_stopped_at.replace(second=0, microsecond=0):
                        detected_slugs.append('stopped_at')

                # --- [BLOQUEIO] Verificação de Alterações ---
                # Comparamos cada campo para garantir que houve mudança real
                status_mudou = new_status and incident.status_id != new_status.id
                impacto_mudou = incident.is_impact_active != is_impact_active
                previsao_mudou = False
                curr_exp = incident.expected_at.replace(second=0, microsecond=0) if incident.expected_at else None
                final_exp = new_expected_at.replace(second=0, microsecond=0) if new_expected_at else None
                if curr_exp != final_exp:
                    previsao_mudou = True

                impact_level_mudou = new_impact_level and incident.impact_level_id != new_impact_level.id
                impact_type_mudou = new_impact_type and incident.impact_type_id != new_impact_type.id
                
                # Campos de normalização (se visíveis/enviados)
                outros_campos_mudaram = False
                if note_text and note_text != (incident.note or ''): outros_campos_mudaram = True
                if rfo_text and rfo_text != (incident.rfo or ''): outros_campos_mudaram = True
                if root_cause_id and incident.root_cause_id != (str(incident.root_cause_id) if incident.root_cause_id else ''): outros_campos_mudaram = True

                stopped_at_mudou = False
                if new_stopped_at:
                    curr_stop = incident.stopped_at.replace(second=0, microsecond=0) if incident.stopped_at else None
                    if curr_stop != new_stopped_at.replace(second=0, microsecond=0):
                        stopped_at_mudou = True
                elif incident.stopped_at is not None:
                    stopped_at_mudou = True

                protocolo_mudou = (incident.provider_protocol or '') != provider_protocol or incident.no_provider_protocol != no_provider_protocol
                anexo_mudou = len(attachments_list) > 0
                
                has_changes = status_mudou or impacto_mudou or previsao_mudou or impact_level_mudou or impact_type_mudou or outros_campos_mudaram or stopped_at_mudou or protocolo_mudou or anexo_mudou

                if not has_changes and not comment_text:
                    response = HttpResponse(status=200) 
                    response['HX-Trigger'] = json.dumps({"erroValidacao": "Nenhuma mudança ou nota técnica informada para salvar."})
                    response['HX-Reswap'] = 'none'
                    return response

                # 2. Comentário Automático de Sistema (se o operador não preencher nada)
                if not comment_text:
                    mensagens_sistema = []

                    if 'impact' in detected_slugs:
                        if is_impact_active:
                            mensagens_sistema.append("A afetação foi iniciada")
                        else:
                            mensagens_sistema.append("A afetação foi encerrada")
                            
                    if 'expected_at' in detected_slugs:
                        if new_expected_at:
                            tz = timezone.get_current_timezone()
                            dt_str = new_expected_at.astimezone(tz).strftime('%d/%m/%Y às %H:%M')
                            mensagens_sistema.append(f"A previsão foi atualizada para {dt_str}")
                        else:
                            mensagens_sistema.append("A previsão foi removida")
                            
                    if 'impact_level' in detected_slugs and new_impact_level:
                        mensagens_sistema.append(f"O nível de impacto foi alterado para '{new_impact_level.name}'")
                        
                    if 'impact_type' in detected_slugs and new_impact_type:
                        mensagens_sistema.append(f"O tipo de impacto foi alterado para '{new_impact_type.name}'")
                        
                    if 'stopped_at' in detected_slugs:
                        if new_stopped_at:
                            tz = timezone.get_current_timezone()
                            dt_str = new_stopped_at.astimezone(tz).strftime('%d/%m/%Y às %H:%M')
                            mensagens_sistema.append(f"A previsão de despausa foi atualizada para {dt_str}")
                        else:
                            mensagens_sistema.append("A previsão de despausa foi removida")
                            
                    if new_status and incident.status_id != new_status.id:
                        mensagens_sistema.append(f"O status do chamado foi alterado para '{new_status.name}'")

                    if protocolo_mudou:
                        if provider_protocol:
                            mensagens_sistema.append(f"Protocolo da operadora atualizado para: {provider_protocol}")
                        elif no_provider_protocol:
                            mensagens_sistema.append("Marcado como: Sem protocolo")
                        else:
                            mensagens_sistema.append("Informação de protocolo de operadora removida")

                    if anexo_mudou:
                        if len(attachments_list) > 1:
                            mensagens_sistema.append(f"{len(attachments_list)} novos anexos foram enviados")
                        else:
                            mensagens_sistema.append(f"Um novo anexo foi enviado ('{attachments_list[0].name}')")

                    if mensagens_sistema:
                        comment_text = "[SISTEMA] " + ". ".join(mensagens_sistema) + "."
                    else:
                        comment_text = "[SISTEMA] Atualização de rotina."

                # 3. Cálculo de Tempo Decorrido
                last_update = incident.last_history_update_at or incident.occured_at or now
                time_elapsed = max(0, int((user_updated_at - last_update).total_seconds() / 60))

                # 4. Sincronização e Persistência (Transacional)
                with transaction.atomic():
                    # [REGRA] Se já estava normalizado, não gera update de histórico (Timeline)
                    estava_normalizado = incident.status.name.lower() == 'normalizado'

                    # Atualiza o Incidente pai
                    incident.status = new_status or incident.status
                    incident.impact_level = new_impact_level or incident.impact_level
                    incident.impact_type = new_impact_type or incident.impact_type
                    incident.expected_at = new_expected_at or incident.expected_at
                    incident.stopped_at = new_stopped_at or incident.stopped_at
                    incident.is_impact_active = is_impact_active
                    incident.last_history_update_at = now # Registro absoluto
                    incident.last_manual_update_at = user_updated_at # Prioriza manual se houver
                    
                    # Outras relações específicas da View
                    if new_status and new_status.name.lower() == 'escalonado' and assigned_to_id:
                        incident.assigned_to_id = assigned_to_id
                    
                    # [NOVO] Persistência de Protocolo de Operadora
                    incident.provider_protocol = provider_protocol
                    incident.no_provider_protocol = no_provider_protocol
                    
                    # Detecção de Encerramento (Campos extras de normalização)
                    is_norm = incident.status.name.lower() in ['normalizado', 'resolvido', 'encerrado']
                    if is_norm:
                        if root_cause_id: incident.root_cause_id = root_cause_id
                        if note_text: incident.note = note_text
                        if rfo_text: incident.rfo = rfo_text
                        
                        # Se houver uma data real de normalização informada, ela sincroniza com o resolved_at
                        if resolved_at_str:
                            res_dt = parse_datetime(resolved_at_str)
                            if res_dt:
                                if timezone.is_naive(res_dt):
                                    res_dt = timezone.make_aware(res_dt)
                                incident.resolved_at = res_dt
                        elif not incident.resolved_at:
                            # Caso não informada mas o status seja de fechamento, usa o agora
                            incident.resolved_at = now

                    incident.save()

                    # Só cria o registro de atualização no histórico se NÃO estava normalizado anteriormente
                    if not estava_normalizado:
                        update_obj = UpdateIncident.objects.create(
                            incident=incident,
                            created_by=user,
                            status=incident.status,
                            is_impact_active=incident.is_impact_active,
                            comment=comment_text,
                            user_updated_at=user_updated_at,
                            impact_level=incident.impact_level,
                            impact_type=incident.impact_type,
                            expected_at=incident.expected_at,
                            stopped_at=incident.stopped_at,
                            time_elapsed=time_elapsed
                        )

                        # Salva os múltiplos anexos
                        if attachments_list:
                            for att in attachments_list:
                                att_obj = UpdateAttachment.objects.create(
                                    update=update_obj,
                                    file=att
                                )
                                update_obj.attachments.add(att_obj)

                        # Atribui as tags de mudança
                        if detected_slugs:
                            tags = UpdateTag.objects.filter(slug__in=detected_slugs)
                            update_obj.tags.set(tags)
                        
                        # Tag de Novo Comentário (se for manual)
                        if not comment_text.startswith('[SISTEMA]'):
                            comment_tag = UpdateTag.objects.filter(slug='is_new_comment').first()
                            if comment_tag: update_obj.tags.add(comment_tag)

                return True
                
            result = await save_update()
            if isinstance(result, HttpResponse):
                return result
            
            source_param = "?source=dashboard" if request.GET.get('source') == 'dashboard' else ""
            
            # [HTMX] Exibe sucesso por 1s e depois carrega os detalhes automaticamente
            response = HttpResponse(f"""
                <div class="text-center py-5 animate-fade-in">
                    <i class="bi bi-check-circle-fill text-success" style="font-size: 3rem;"></i>
                    <h5 class="mt-3 fw-bold" style="color: var(--text-main);">Atualização Registrada com Sucesso!</h5>
                    <p class="text-muted" style="font-size: 11px;">Redirecionando para detalhes em 1 segundo...</p>
                    
                    <!-- Gatilho HTMX para carregar os detalhes após 1s -->
                    <div hx-get="/incidents/detalhe-ajax/{protocolo}/{source_param}" 
                         hx-trigger="load delay:1s" 
                         hx-target="#conteudoAtualizacao">
                    </div>
                </div>

                <!-- Ajuste OOB para o título do Offcanvas -->
                <div id="offcanvasAtualizacaoLabel" hx-swap-oob="innerHTML">
                    <i class="bi bi-info-circle-fill me-2"></i>Detalhes do Chamado (Pós-Atualização)
                </div>
            """)
            response['HX-Trigger'] = 'atualizacaoConcluida'
            return response

        # --- [GET] LÓGICA DE APRESENTAÇÃO DO FORMULÁRIO COM DADOS DO BANCO ---
        @sync_to_async
        def get_update_form_data():
            incident = Incident.objects.select_related(
                'status', 'incident_type', 'site', 'circuit', 'device',
                'impact_type', 'impact_level', 'client_type', 'sla'
            ).prefetch_related(
                'updates__created_by', 'updates__tags'
            ).filter(Q(protocol_number=protocolo) | Q(mk_protocol=protocolo)).first()

            if not incident:
                return None

            # Filtra os status estáticos solicitados (Escalonado agora é permitido)
            lista_status = list(Status.objects.exclude(name='Excluido').order_by('name'))
            lista_tipos_impacto = list(ImpactType.objects.all().order_by('id'))
            lista_niveis_impacto = list(ImpactLevel.objects.all().order_by('id'))
            lista_tipos_cliente = list(ClientType.objects.all().order_by('id'))
            lista_slas = list(SLA.objects.all().order_by('id'))
            lista_causas_raiz = list(RootCause.objects.all().order_by('name'))
            
            # Lista de usuários para escalonamento (apenas eylon.toda por enquanto)
            lista_usuarios = list(User.objects.filter(username='eylon.toda'))

            # Designador
            tipo_nome = incident.incident_type.name if incident.incident_type else "N/D"
            if tipo_nome == 'Site':
                designador_nome = incident.site.facility if (incident.site and incident.site.facility) else (incident.site.name if incident.site else "S/S")
            elif tipo_nome in ['Backbone', 'Core']:
                designador_nome = incident.circuit.name if incident.circuit else "S/C"
            elif tipo_nome == 'R.A.':
                designador_nome = incident.device.name if incident.device else "S/D"
            else:
                designador_nome = "N/D"

            # Histórico ordenado com Tags M2M
            historico_updates = incident.updates.annotate(
                display_time=Coalesce(F('user_updated_at'), F('created_at'))
            ).select_related('created_by').prefetch_related('tags', 'attachments').order_by('-display_time')

            return {
                'incident': incident,
                'designador_nome': designador_nome,
                'is_third_party': is_third_party_incident(incident),
                'lista_status': lista_status,
                'lista_tipos_impacto': lista_tipos_impacto,
                'lista_niveis_impacto': lista_niveis_impacto,
                'lista_tipos_cliente': lista_tipos_cliente,
                'lista_slas': lista_slas,
                'lista_causas_raiz': lista_causas_raiz,
                'lista_usuarios': lista_usuarios,
                'historico_updates': historico_updates,
                'is_dashboard': request.GET.get('source') == 'dashboard',
                'now': timezone.now()
            }

        context_data = await get_update_form_data()
        
        if not context_data:
            return HttpResponse(f"<div class='alert alert-danger m-3'>Protocolo {protocolo} não encontrado.</div>", status=404)
        
        return await sync_to_async(render)(request, 'users/partials/atualizacao_offcanvas.html', context_data)

    except Exception as e:
        error_msg = f"<strong>Erro de Processamento:</strong> {str(e)}<br><small>{traceback.format_exc()}</small>"
        return HttpResponse(f"<div class='alert alert-danger m-3' style='font-size: 11px;'>{error_msg}</div>", status=200)


# --- [BOTÃO PENCIL] View para Edição Completa do Chamado ---
async def editar_incidente_ajax(request, protocolo):
    """
    View responsável por carregar o Offcanvas de Edição Mestra (Pencil).
    Permite alterar dados estruturais que não estão no fluxo de atualização rápida.
    """
    try:
        user = await request.auser()
        if not user.is_authenticated:
            return HttpResponse("Não autorizado", status=401)

        # --- [POST] SALVAMENTO DE DADOS ESTRUTURAIS ---
        if request.method == 'POST':
            @sync_to_async
            def save_structural_edit():
                try:
                    with transaction.atomic():
                        incident = Incident.objects.select_related('incident_type').filter(Q(protocol_number=protocolo) | Q(mk_protocol=protocolo)).first()
                        if not incident: return "Protocolo não encontrado."
                        
                        def clean_id(val):
                            if not val or str(val).strip().lower() in ['none', 'null', '']:
                                return None
                            try:
                                return int(val)
                            except (ValueError, TypeError):
                                return None

                        # Valores Atuais para Comparação
                        old_occured = incident.occured_at.replace(second=0, microsecond=0) if incident.occured_at else None
                        old_expected = incident.expected_at.replace(second=0, microsecond=0) if incident.expected_at else None

                        # Novos Valores Sanitizados
                        new_protocol = request.POST.get('mk_protocol', '').strip()
                        new_type_id = clean_id(request.POST.get('incident_type_id'))
                        new_occured_str = request.POST.get('occured_at')

                        # Validação de Protocolo
                        if not new_protocol:
                            response = HttpResponse(status=200)
                            response['HX-Trigger'] = json.dumps({"erroValidacao": "O protocolo é obrigatório."})
                            response['HX-Reswap'] = 'none'
                            return response
                        
                        import re
                        if not re.match(r'^\d{4}\.\d{1,5}$', new_protocol):
                            response = HttpResponse(status=200)
                            response['HX-Trigger'] = json.dumps({"erroValidacao": "Formato de protocolo inválido (esperado XXXX.Y)."})
                            response['HX-Reswap'] = 'none'
                            return response

                        if new_protocol != incident.mk_protocol:
                            duplicado = Incident.objects.exclude(status__name__iexact='Excluido').exclude(id=incident.id).filter(mk_protocol=new_protocol).exists()
                            if duplicado:
                                response = HttpResponse(status=200)
                                response['HX-Trigger'] = json.dumps({"erroValidacao": f"O protocolo {new_protocol} já está em uso por outro incidente."})
                                response['HX-Reswap'] = 'none'
                                return response
                        
                        temp_occ = parse_datetime(new_occured_str) if new_occured_str else None
                        if temp_occ and timezone.is_naive(temp_occ):
                            temp_occ = timezone.make_aware(temp_occ)
                        new_occured = temp_occ.replace(second=0, microsecond=0) if temp_occ else None
                        
                        new_expected = None
                        
                        # Detecção de Mudanças
                        mensagens_sistema = []
                        detected_slugs = []
                        
                        if incident.mk_protocol != new_protocol: 
                            mensagens_sistema.append(f"Protocolo MK alterado para {new_protocol}")
                        
                        if incident.incident_type_id != new_type_id: 
                            mensagens_sistema.append(f"Tipo de incidente alterado")
                        
                        if old_occured != new_occured: 
                            mensagens_sistema.append(f"Horário de início da ocorrência ajustado")

                        if request.POST.get('description', '') != (incident.description or ''): 
                            mensagens_sistema.append("Descrição do incidente atualizada")
                        
                        new_sla_id = clean_id(request.POST.get('sla_id'))
                        if new_sla_id != incident.sla_id: 
                            mensagens_sistema.append("SLA de atendimento alterado")
                            detected_slugs.append("sla")

                        new_client_type_id = clean_id(request.POST.get('client_type_id'))
                        if new_client_type_id != incident.client_type_id: 
                            mensagens_sistema.append("Segmento de cliente afetado alterado")
                            detected_slugs.append("client_type")

                        if clean_id(request.POST.get('detection_source_id')) != incident.detection_source_id: 
                            mensagens_sistema.append("Fonte de detecção alterada")
                        
                        if clean_id(request.POST.get('reported_symptom_id')) != incident.reported_symptom_id: 
                            mensagens_sistema.append("Sintoma reportado alterado")
                            
                        if clean_id(request.POST.get('site_id')) != incident.site_id: 
                            mensagens_sistema.append("Designador de Site alterado")
                            
                        if clean_id(request.POST.get('circuit_id')) != incident.circuit_id: 
                            mensagens_sistema.append("Designador de Circuito alterado")
                            
                        if clean_id(request.POST.get('device_id')) != incident.device_id: 
                            mensagens_sistema.append("Designador de Dispositivo alterado")
                        
                        # Verificação de M2M
                        regioes_novas = set(clean_id(r) for r in request.POST.getlist('affected_regions') if clean_id(r))
                        regioes_atuais = set(r.id for r in incident.affected_regions.all())
                        if regioes_novas != regioes_atuais:
                            mensagens_sistema.append("Cidades afetadas atualizadas")

                        # [NOVO] Protocolo de Operadora
                        new_provider_protocol = request.POST.get('provider_protocol', '').strip()
                        new_no_provider_protocol = request.POST.get('no_provider_protocol') == 'on'
                        if (incident.provider_protocol or '') != new_provider_protocol or incident.no_provider_protocol != new_no_provider_protocol:
                            if new_provider_protocol:
                                mensagens_sistema.append(f"Protocolo da operadora atualizado para: {new_provider_protocol}")
                            elif new_no_provider_protocol:
                                mensagens_sistema.append("Marcado como: Sem protocolo")
                            else:
                                mensagens_sistema.append("Informação de protocolo de operadora removida")


                        has_changes = bool(mensagens_sistema)

                        if not has_changes:
                            response = HttpResponse(status=200)
                            response['HX-Trigger'] = json.dumps({"erroValidacao": "Nenhuma alteração detectada."})
                            response['HX-Reswap'] = 'none'
                            return response

                        # Aplicação das Mudanças
                        incident.mk_protocol = new_protocol
                        incident.incident_type_id = new_type_id
                        incident.detection_source_id = clean_id(request.POST.get('detection_source_id'))
                        incident.reported_symptom_id = clean_id(request.POST.get('reported_symptom_id'))
                        incident.sla_id = new_sla_id
                        incident.client_type_id = new_client_type_id
                        
                        tipo_obj = IncidentType.objects.filter(id=incident.incident_type_id).first()
                        tipo = tipo_obj.name if tipo_obj else "N/D"
                        
                        incident.site_id = clean_id(request.POST.get('site_id')) if tipo == 'Site' else None
                        incident.circuit_id = clean_id(request.POST.get('circuit_id')) if tipo in ['Backbone', 'Core'] else None
                        incident.device_id = clean_id(request.POST.get('device_id')) if tipo in ['R.A.', 'Equipamento'] else None
                        
                        if new_occured_str: incident.occured_at = parse_datetime(new_occured_str)
                        # [NOVO] Protocolo de Operadora
                        incident.provider_protocol = new_provider_protocol
                        incident.no_provider_protocol = new_no_provider_protocol
                        
                        incident.description = request.POST.get('description', '')
                        
                        incident.last_manual_update_at = timezone.now()
                        incident.save()
                        
                        regioes = request.POST.getlist('affected_regions')
                        incident.affected_regions.set(regioes)

                        # Só cria o registro de atualização no histórico se NÃO estiver normalizado
                        # (Alterações estruturais em chamados fechados não devem sujar a timeline)
                        if incident.status.name.lower() != 'normalizado':
                            comment_text = f"[SISTEMA] Alteração estrutural: {'. '.join(mensagens_sistema)}."
                            update_obj = UpdateIncident.objects.create(
                                incident=incident,
                                created_by=user,
                                status=incident.status,
                                is_impact_active=incident.is_impact_active,
                                comment=comment_text,
                                user_updated_at=timezone.now(),
                                impact_level=incident.impact_level,
                                impact_type=incident.impact_type,
                                expected_at=incident.expected_at,
                                time_elapsed=0
                            )
                            if detected_slugs:
                                tags = UpdateTag.objects.filter(slug__in=detected_slugs)
                                update_obj.tags.set(tags)
                        
                        return {'new_protocol': new_protocol}
                except Exception as e:
                    response = HttpResponse(status=200)
                    response['HX-Trigger'] = json.dumps({"erroValidacao": f"Erro técnico: {str(e)}"})
                    response['HX-Reswap'] = 'none'
                    return response

            result = await save_structural_edit()
            if isinstance(result, HttpResponse):
                return result
            
            if isinstance(result, dict) and 'new_protocol' in result:
                new_proto = result['new_protocol']
                source_param = "?source=dashboard" if request.GET.get('source') == 'dashboard' else ""
                # [HTMX] Exibe sucesso por 1s e depois carrega os detalhes automaticamente
                response = HttpResponse(f"""
                    <div class="text-center py-5 animate-fade-in">
                        <i class="bi bi-check-circle-fill text-success" style="font-size: 3rem;"></i>
                        <h5 class="mt-3 fw-bold" style="color: var(--text-main);">Alterações Estruturais Salvas!</h5>
                        <p class="text-muted" style="font-size: 11px;">Redirecionando para detalhes em 1 segundo...</p>
                        
                        <!-- Gatilho HTMX para carregar os detalhes após 1s -->
                        <div hx-get="/incidents/detalhe-ajax/{new_proto}/{source_param}" 
                             hx-trigger="load delay:1s" 
                             hx-target="#conteudoEditar">
                        </div>
                    </div>

                    <!-- Ajuste OOB para o título do Offcanvas -->
                    <div id="offcanvasEditarLabel" hx-swap-oob="innerHTML">
                        <i class="bi bi-info-circle-fill me-2"></i>Detalhes do Chamado (Pós-Edição)
                    </div>
                """)
                response['HX-Trigger'] = json.dumps({"atualizacaoConcluida": True})
                return response
            
            return HttpResponse(f"<div class='alert alert-danger m-2'>{result}</div>", status=200)

        # --- [GET] CARREGAMENTO DO FORMULÁRIO ---
        @sync_to_async
        def get_edit_context():
            incident = Incident.objects.select_related(
                'status', 'incident_type', 'site', 'circuit', 'device', 'detection_source', 'reported_symptom'
            ).filter(Q(protocol_number=protocolo) | Q(mk_protocol=protocolo)).first()
            
            if not incident: return None
            

            return {
                'incident': incident,
                'is_third_party': is_third_party_incident(incident),

                'lista_status': list(Status.objects.all().order_by('name')),
                'lista_tipos': list(IncidentType.objects.all().order_by('name')),
                'lista_sintomas': list(Symptom.objects.all().order_by('name')),
                'lista_fontes': list(DetectionSource.objects.all().order_by('name')),
                'lista_slas': list(SLA.objects.all().order_by('id')),
                'lista_tipos_cliente': list(ClientType.objects.exclude(name='Em Análise').order_by('id')),
                'lista_regioes': list(Region.objects.all().order_by('name')),
                
                # Listas de infra categorizadas (Apenas ATIVOS)
                'lista_sites': list(Site.objects.filter(netbox_status__slug='active').order_by('name')),
                
                'lista_circuitos_backbone': [{
                    'id': c.id, 
                    'name': c.name, 
                    'site_a_full_name': c.site_a.name if c.site_a else "",
                    'site_z_full_name': c.site_z.name if c.site_z else ""
                } for c in Circuit.objects.select_related('site_a', 'site_z').filter(
                    netbox_status__slug='active',
                    type__slug__in=['ce', 'rede-backbone-terceiros', 'rede-backbone-prpria']
                ).order_by('name')],
                
                'lista_circuitos_core': [{
                    'id': c.id,
                    'name': c.name,
                    'provider_name': c.provider.name if c.provider else "N/D"
                } for c in Circuit.objects.select_related('provider').filter(
                    netbox_status__slug='active',
                    type__slug__in=['capacidade-ip', 'ptt']
                ).order_by('name')],
                
                'lista_devices': [{
                    'id': d.id,
                    'name': d.name,
                    'region_name': d.site.region.name if d.site and d.site.region else "N/D"
                } for d in Device.objects.select_related('site__region').filter(
                    netbox_status__slug='active', 
                    role__slug='olt'
                ).order_by('name')],
                'is_dashboard': request.GET.get('source') == 'dashboard',
            }

        context = await get_edit_context()
        if not context: return HttpResponse("Protocolo não encontrado", status=404)
        
        return await sync_to_async(render)(request, 'users/partials/editar_incidente_offcanvas.html', context)

    except Exception as e:
        return HttpResponse(f"<div class='alert alert-danger m-2'>Erro crítico: {str(e)}</div>", status=200)


# ==============================================================================
# APIs DE DADOS (DASHBOARDS E TABELAS)
# ==============================================================================

async def api_dashboard_stats(request):
    """
    Alimenta os balões do topo com a contagem real de incidentes.
    """
    user = await request.auser()
    if not user.is_authenticated:
        return JsonResponse({'error': 'Não autorizado'}, status=401)

    cache_key = 'dashboard_stats_data'
    stats_data = cache.get(cache_key)
    
    if not stats_data:
        @sync_to_async
        def get_stats():
            now = timezone.now()
            last_24h = now - timezone.timedelta(hours=24)
            active_statuses = ['Em abertura', 'Em andamento', 'Pendente terceiros', 'Pendente resgate', 'Escalonado', 'Em validação']
            return Incident.objects.aggregate(
                em_andamento=Count('id', filter=Q(status__name__in=active_statuses)),
                normalizado=Count('id', filter=Q(status__name__iexact='Normalizado', resolved_at__gte=last_24h)),
                sem_afetacao=Count('id', filter=Q(status__name__in=active_statuses, is_impact_active=False)),
                com_afetacao=Count('id', filter=Q(status__name__in=active_statuses, is_impact_active=True))
            )

        try:
            stats = await get_stats()
            stats_data = {
                'em_andamento_count': stats['em_andamento'],
                'normalizado_count': stats['normalizado'],
                'sem_afetacao_count': stats['sem_afetacao'],
                'com_afetacao_count': stats['com_afetacao'],
            }
            cache.set(cache_key, stats_data, 15) # Cache por 15 segundos
        except Exception as e:
            return JsonResponse({'error': f'Erro interno: {str(e)}'}, status=500)

    stats_data['timestamp'] = timezone.now().strftime('%H:%M:%S')
    return JsonResponse(stats_data)

async def api_incidents_list(request):
    """
    Fornece o payload JSON que monta a tabela DataTables.
    """
    user = await request.auser()
    if not user.is_authenticated:
        return JsonResponse({'error': 'Não autorizado'}, status=401)
    
    @sync_to_async
    def get_data():
        hoje = timezone.now()
        status_filter = request.GET.get('status_filter')

        # 1. Retomada Automática (Processa antes de montar a lista)
        resumable = Incident.objects.filter(status__name='Pausado', stopped_at__lte=hoje)
        if resumable.exists():
            try:
                status_andamento = Status.objects.get(name='Em andamento')
                for r_inc in resumable:
                    r_inc.status = status_andamento
                    r_inc.last_history_update_at = hoje
                    r_inc.save()
                    UpdateIncident.objects.create(
                        incident=r_inc,
                        created_by=None, 
                        status=status_andamento,
                        is_impact_active=r_inc.is_impact_active,
                        comment="[SISTEMA] Chamado retomado automaticamente após fim da pausa programada.",
                        time_elapsed=0
                    )
            except Status.DoesNotExist:
                pass

        from django.db.models import Prefetch
        
        updates_prefetch = Prefetch(
            'updates',
            queryset=UpdateIncident.objects.order_by('-created_at'),
            to_attr='latest_updates'
        )

        queryset = Incident.objects.exclude(
            status__name__iexact='Excluido'
        )

        if status_filter == 'abertura':
            queryset = queryset.filter(status__name='Em abertura')
        elif status_filter == 'regular':
            queryset = queryset.exclude(status__name='Em abertura')

        incidents = queryset.select_related(
            'status', 'incident_type', 'circuit', 'site', 'device', 'assigned_to'
        ).prefetch_related(
            updates_prefetch
        ).only(
            'id', 'protocol_number', 'mk_protocol', 'occured_at', 'expected_at', 'resolved_at', 'description', 'status__name', 
            'incident_type__name', 'is_impact_active', 'last_history_update_at', 'last_manual_update_at',
            'site__name', 'site__facility', 'circuit__name', 'device__name',
            'assigned_to__username', 'stopped_at'
        ).annotate(
            last_event=Coalesce(F('last_manual_update_at'), F('occured_at'))
        ).order_by('-last_event')
        
        data_list = []
        for inc in incidents:
            dt_last_event_local = timezone.localtime(inc.last_event) if inc.last_event else None
            dt_occured_local = timezone.localtime(inc.occured_at) if inc.occured_at else None
            
            # Inatividade = Tempo desde a última atualização (ou criação se nunca atualizado)
            # Se normalizado, consideramos 0 para não poluir ou atrapalhar a ordenação
            is_normalizado = inc.status.name.lower() == 'normalizado'
            
            is_pausado = inc.status.name.lower() == 'pausado'
            
            paused_minutes = 0
            paused_percent = 0
            if is_pausado and inc.stopped_at:
                # Previsão de despausa no futuro
                last_update = inc.last_manual_update_at or inc.occured_at
                total_pause_duration = (inc.stopped_at - last_update).total_seconds()
                remaining_pause = (inc.stopped_at - hoje).total_seconds()
                
                paused_minutes = int(remaining_pause / 60) if remaining_pause > 0 else 0
                if total_pause_duration > 0:
                    # Progresso reduzindo (conforme tempo se aproxima, a barra diminui)
                    paused_percent = max(0, min(100, (remaining_pause / total_pause_duration) * 100))
                
                inactivity_minutes = 0 # Não conta inatividade se pausado
            elif is_normalizado:
                inactivity_minutes = 0
            else:
                last_update = inc.last_manual_update_at or inc.occured_at
                diff_delta = hoje - last_update if last_update else None
                inactivity_minutes = int(diff_delta.total_seconds() / 60) if diff_delta else 0

            tipo_nome = inc.incident_type.name if inc.incident_type else ""
            designator = "N/D"

            if tipo_nome == 'Site':
                facility = inc.site.facility if inc.site and inc.site.facility else (inc.site.name if inc.site else "S/S")
                site_name = inc.site.name if inc.site else "S/S"
                designator = f"{facility} - {site_name}"
            elif tipo_nome in ['Backbone', 'Core']:
                designator = inc.circuit.name if inc.circuit else "S/C"
            elif tipo_nome in ['R.A.', 'Equipamento']:
                designator = inc.device.name if inc.device else "S/D"

            # --- CÁLCULO DE PROGRESSO (PREVISÃO) ---
            progress_data = None
            if inc.occured_at and inc.expected_at:
                total_duration = (inc.expected_at - inc.occured_at).total_seconds()
                elapsed_duration = (hoje - inc.occured_at).total_seconds()
                
                if total_duration > 0:
                    percent = min(100, max(0, (elapsed_duration / total_duration) * 100))
                else:
                    percent = 100 if hoje >= inc.expected_at else 0

                remaining_seconds = (inc.expected_at - hoje).total_seconds()
                is_overdue = remaining_seconds < 0
                
                if is_overdue:
                    rem_min = int(abs(remaining_seconds) / 60)
                    label = format_duration_human(rem_min)
                else:
                    rem_min = int(remaining_seconds / 60)
                    if rem_min < 60:
                        label = f"{rem_min} min"
                    else:
                        label = f"{int(rem_min/60)}h {rem_min%60}m"

                progress_data = {
                    'percent': percent,
                    'label': label,
                    'is_overdue': is_overdue,
                    'remaining_minutes': int(abs(remaining_seconds) / 60)
                }

            dt_expected_local = timezone.localtime(inc.expected_at) if inc.expected_at else None
            
            latest_update = inc.latest_updates[0] if hasattr(inc, 'latest_updates') and inc.latest_updates else None
            last_update_text = latest_update.comment if latest_update else ""

            data_list.append({
                'id': inc.id,
                'protocol': inc.mk_protocol or "",
                'protocol_internal': inc.protocol_number or "",
                'timestamp': dt_last_event_local.strftime('%d/%m/%Y %H:%M') if dt_last_event_local else "N/D",
                'timestamp_iso': dt_last_event_local.isoformat() if dt_last_event_local else None,
                'occured_at': dt_occured_local.strftime('%d/%m/%Y %H:%M') if dt_occured_local else "N/D",
                'occured_at_iso': dt_occured_local.isoformat() if dt_occured_local else None,
                'expected_at': dt_expected_local.strftime('%d/%m/%Y %H:%M') if dt_expected_local else None,
                'last_update_text': last_update_text,
                'designator': designator,
                'type': tipo_nome,
                'description': inc.description[:100] + "..." if inc.description and len(inc.description) > 100 else (inc.description or ""),
                'status_name': inc.status.name if inc.status else "Desconhecido",
                'is_impact_active': inc.is_impact_active,
                'inactivity_minutes': inactivity_minutes,
                'is_paused': is_pausado,
                'paused_minutes': paused_minutes,
                'paused_percent': paused_percent,
                'assigned_to': inc.assigned_to.username if inc.assigned_to else "Livre",
                'progress': progress_data,
                'resolved_at_iso': inc.resolved_at.isoformat() if inc.resolved_at else None,
            })
        return data_list

    try:
        data = await get_data()
        return JsonResponse({'incidents': data})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

async def resgatar_incidente_ajax(request, protocolo):
    """
    Atribui o incidente ao usuário logado.
    """
    user = await request.auser()
    if not user.is_authenticated:
        return JsonResponse({'success': False, 'error': 'Não autenticado'}, status=401)
    
    @sync_to_async
    def do_rescue():
        try:
            from django.db.models import Q
            from apps.incidents.models import Incident, Status
            incident = Incident.objects.filter(Q(protocol_number=protocolo) | Q(mk_protocol=protocolo)).first()
            if not incident:
                return False
            if incident.assigned_to == user:
                return True # Já está atribuído
            
            # --- LÓGICA DE TRANSIÇÃO DE STATUS ---
            # Busca no histórico o último status que NÃO seja 'Pendente resgate'
            # history.exclude(status__name='Pendente resgate') pega o estado anterior ao release
            last_status_record = incident.history.exclude(status__name='Pendente resgate').order_by('-history_date').first()
            
            status_em_andamento = Status.objects.filter(name='Em andamento').first()
            
            if last_status_record and last_status_record.status:
                prev_status = last_status_record.status
                # Exceção: Se era 'Em abertura', vai para 'Em andamento'
                if prev_status.name == 'Em abertura':
                    incident.status = status_em_andamento
                else:
                    incident.status = prev_status
            else:
                # Fallback de segurança
                incident.status = status_em_andamento

            incident.assigned_to = user
            incident.save()
            return True
        except Exception as e:
            print(f"Erro ao resgatar: {e}")
            return False

    success = await do_rescue()
    return JsonResponse({'success': success})

async def liberar_incidente_ajax(request, protocolo):
    """
    Remove a atribuição do incidente (deixa Livre).
    """
    user = await request.auser()
    if not user.is_authenticated:
        return JsonResponse({'success': False, 'error': 'Não autenticado'}, status=401)
    
    @sync_to_async
    def do_release():
        try:
            from django.db.models import Q
            from apps.incidents.models import Incident, Status
            incident = Incident.objects.filter(Q(protocol_number=protocolo) | Q(mk_protocol=protocolo)).first()
            if not incident:
                return False
            
            # --- LÓGICA DE TRANSIÇÃO DE STATUS ---
            status_pendente = Status.objects.filter(name='Pendente resgate').first()
            if status_pendente:
                incident.status = status_pendente

            incident.assigned_to = None
            incident.save()
            return True
        except Exception as e:
            print(f"Erro ao liberar: {e}")
            return False

    success = await do_release()
    return JsonResponse({'success': success})

async def excluir_incidente_ajax(request, protocolo):
    """
    Muda o status do incidente para 'Excluido' (Soft Delete).
    """
    user = await request.auser()
    if not user.is_authenticated:
        return JsonResponse({'success': False, 'error': 'Não autenticado'}, status=401)
    
    @sync_to_async
    def do_delete():
        try:
            from django.db.models import Q
            from apps.incidents.models import Incident, Status
            incident = Incident.objects.filter(Q(protocol_number=protocolo) | Q(mk_protocol=protocolo)).first()
            if not incident:
                return False
            status_excluido = Status.objects.filter(name__iexact='Excluido').first()
            if status_excluido:
                incident.status = status_excluido
                incident.save()
                return True
            return False
        except Exception as e:
            print(f"Erro ao excluir: {e}")
            return False

    success = await do_delete()
    return JsonResponse({'success': success})
async def novo_incidente_ajax(request):
    """
    Retorna o formulário de abertura de novo incidente para o Modal.
    """
    try:
        user = await request.auser()
        if not user.is_authenticated:
            return HttpResponse("<div class='alert alert-warning m-3'>Sessão expirada.</div>", status=401)

        @sync_to_async
        def get_context():
            # Ordenação manual para SLA (Extraindo horas)
            slas = list(SLA.objects.all())
            def get_sla_hours(s):
                if 'h' in s.name.lower():
                    try: return int(s.name.lower().replace('h',''))
                    except: return 999
                return 1000
            slas.sort(key=get_sla_hours)

            # Ordenação manual para Nível de Impacto
            niveis_ordem = [
                'Nenhum cliente', '01 à 31 clientes', '32 à 100 clientes', 
                '100 à 500 clientes', '500 à 1000 clientes', '1000 à 2000 clientes', 
                '2000 à 5000 clientes', 'Mais de 5000 clientes', 'Todos os clientes'
            ]
            niveis = list(ImpactLevel.objects.exclude(name='Em análise'))
            niveis.sort(key=lambda x: niveis_ordem.index(x.name) if x.name in niveis_ordem else 999)

            # Ordenação para Tipo de Impacto (Total primeiro)
            tipos_impacto = list(ImpactType.objects.all())
            tipos_ordem = ['Total', 'Parcial', 'Intermitente', 'Nenhum']
            tipos_impacto.sort(key=lambda x: tipos_ordem.index(x.name) if x.name in tipos_ordem else 999)

            # Ordenação para Segmento de Cliente
            clientes = list(ClientType.objects.exclude(name='Em Análise'))
            clientes_ordem = ['Banda Larga', 'Dedicado', 'Banda Larga e Dedicado', 'Nenhum']
            clientes.sort(key=lambda x: clientes_ordem.index(x.name) if x.name in clientes_ordem else 999)

            return {
                'lista_status': list(Status.objects.all().order_by('name')),
                'lista_tipos': list(IncidentType.objects.all().order_by('name')),
                'lista_sintomas': list(Symptom.objects.all().order_by('name')),
                'lista_slas': slas,
                'lista_fontes': list(DetectionSource.objects.all().order_by('name')),
                'lista_clientes': clientes,
                'lista_impacto_tipos': tipos_impacto,
                'lista_impacto_niveis': niveis,
                'lista_regioes': list(Region.objects.all().order_by('name')),
                'now': timezone.now(),

                # Infra para Designador
                'lista_sites': list(Site.objects.filter(netbox_status__slug='active').order_by('name')),
                'lista_circuitos_backbone': [{
                    'id': c.id, 
                    'name': c.name, 
                    'site_a_full_name': c.site_a.name if c.site_a else "",
                    'site_z_full_name': c.site_z.name if c.site_z else ""
                } for c in Circuit.objects.select_related('site_a', 'site_z').filter(
                    netbox_status__slug='active',
                    type__slug__in=['ce', 'rede-backbone-terceiros', 'rede-backbone-prpria']
                ).order_by('name')],
                'lista_circuitos_core': [{
                    'id': c.id,
                    'name': c.name,
                    'provider_name': c.provider.name if c.provider else "N/D"
                } for c in Circuit.objects.select_related('provider').filter(
                    netbox_status__slug='active',
                    type__slug__in=['capacidade-ip', 'ptt']
                ).order_by('name')],
                'lista_devices': [{
                    'id': d.id,
                    'name': d.name,
                    'region_name': d.site.region.name if d.site and d.site.region else "N/D"
                } for d in Device.objects.select_related('site__region').filter(
                    netbox_status__slug='active', 
                    role__slug='olt'
                ).order_by('name')],
            }

        if request.method == 'POST':
            # Verificação de Permissão RBAC para disparar Protocolo SEA
            if not request.user.is_superuser and not request.user.groups.filter(ui_permissions__slug='trigger_sea_protocol').exists():
                 return HttpResponse("<div class='alert alert-danger p-2 small'>Você não tem permissão para disparar a geração de novos protocolos SEA.</div>", status=403)
            
            @sync_to_async
            def save_new_incident():
                try:
                    # 1. Resgate de Dados
                    mk_protocol = request.POST.get('mk_protocol', '').strip()
                    status_id = request.POST.get('status_id')
                    incident_type_id = request.POST.get('incident_type_id')
                    reported_symptom_id = request.POST.get('reported_symptom_id')
                    detection_source_id = request.POST.get('detection_source_id')
                    description = request.POST.get('description', '').strip()
                    occured_at_str = request.POST.get('occured_at')
                    
                    # Infra/Designador
                    site_id = request.POST.get('site_id')
                    circuit_id = request.POST.get('circuit_id')
                    device_id = request.POST.get('device_id')
                    
                    # Outros campos
                    sla_id = request.POST.get('sla_id')
                    client_type_id = request.POST.get('client_type_id')
                    impact_type_id = request.POST.get('impact_type_id')
                    impact_level_id = request.POST.get('impact_level_id')
                    is_impact_active = request.POST.get('is_impact_active') == 'True'
                    expected_at_str = request.POST.get('expected_at')
                    affected_regions = request.POST.getlist('affected_regions')

                    # 2. Validação de Campos Obrigatórios
                    erros = []
                    if not mk_protocol: 
                        erros.append("Protocolo")
                    else:
                        # Validação de Formato (4 dígitos + ponto + 1-5 dígitos)
                        import re
                        if not re.match(r'^\d{4}\.\d{1,5}$', mk_protocol):
                            erros.append("Protocolo (Formato inválido: esperado XXXX.Y, ex: 1234.5)")
                        else:
                            # Validação de Duplicidade (Apenas para não excluídos)
                            duplicado = Incident.objects.exclude(status__name__iexact='Excluido').filter(mk_protocol=mk_protocol).first()
                            if duplicado:
                                # Se for duplicado, retornamos um link específico para o container via trigger
                                response = HttpResponse(status=200)
                                link_html = f'<div class="alert alert-warning py-1 px-2 mb-0" style="font-size: 10px; border-left: 3px solid #ffc107;">' \
                                            f'<i class="bi bi-exclamation-triangle-fill me-1"></i> Protocolo já existe. ' \
                                            f'<a href="javascript:void(0)" class="fw-bold text-decoration-underline" style="color: #856404;" ' \
                                            f'hx-get="/incidents/detalhe-ajax/{mk_protocol}/?source=dashboard" hx-target="#conteudoDetalhes" ' \
                                            f'data-bs-toggle="offcanvas" data-bs-target="#offcanvasDetalhes">Ver Incidente {mk_protocol}</a>' \
                                            f'</div>'
                                response['HX-Trigger'] = json.dumps({"protocoloDuplicado": link_html})
                                response['HX-Reswap'] = 'none'
                                return response

                    if not status_id: erros.append("Status Inicial")
                    if not incident_type_id: erros.append("Tipo de Incidente")
                    if not reported_symptom_id: erros.append("Sintoma Reportado")
                    if not description: erros.append("Descrição")
                    if not occured_at_str: erros.append("Início da Ocorrência")
                    
                    # Validação de Designador (Baseada no Tipo)
                    tipo_obj = IncidentType.objects.filter(id=incident_type_id).first() if incident_type_id else None
                    tipo_nome = tipo_obj.name if tipo_obj else ""
                    
                    designador_vazio = False
                    if tipo_nome == 'Site' and not site_id: designador_vazio = True
                    elif tipo_nome in ['Backbone', 'Core'] and not circuit_id: designador_vazio = True
                    elif tipo_nome in ['R.A.', 'Equipamento'] and not device_id: designador_vazio = True
                    
                    if designador_vazio:
                        erros.append("Designador (Site/Circuito/Device)")

                    if erros:
                        response = HttpResponse(status=200)
                        msg = f"Os seguintes campos são obrigatórios: {', '.join(erros)}."
                        response['HX-Trigger'] = json.dumps({"erroValidacao": msg})
                        response['HX-Reswap'] = 'none'
                        return response

                    # 3. Processamento de Datas e Limpeza de IDs Opcionais
                    now = timezone.now()
                    occured_at = parse_datetime(occured_at_str)
                    if occured_at and timezone.is_naive(occured_at):
                        occured_at = timezone.make_aware(occured_at)
                    
                    # Converter strings vazias em None para campos opcionais
                    def clean_id(val):
                        return val if val and val.strip() else None

                    sla_id = clean_id(sla_id)
                    client_type_id = clean_id(client_type_id)
                    impact_type_id = clean_id(impact_type_id)
                    impact_level_id = clean_id(impact_level_id)
                    detection_source_id = clean_id(detection_source_id)
                    reported_symptom_id = clean_id(reported_symptom_id)

                    expected_at = None
                    if is_impact_active and expected_at_str:
                        expected_at = parse_datetime(expected_at_str)
                        if expected_at and timezone.is_naive(expected_at):
                            expected_at = timezone.make_aware(expected_at)
                        if expected_at and expected_at <= (occured_at or now):
                            response = HttpResponse(status=200)
                            response['HX-Trigger'] = json.dumps({"erroValidacao": "A previsão deve ser posterior ao início."})
                            response['HX-Reswap'] = 'none'
                            return response

                    # 4. Persistência
                    with transaction.atomic():
                        incident = Incident.objects.create(
                            mk_protocol=mk_protocol,
                            status_id=status_id,
                            incident_type_id=incident_type_id,
                            reported_symptom_id=reported_symptom_id,
                            detection_source_id=detection_source_id,
                            description=description,
                            occured_at=occured_at,
                            expected_at=expected_at,
                            sla_id=sla_id,
                            client_type_id=client_type_id,
                            impact_type_id=impact_type_id,
                            impact_level_id=impact_level_id,
                            is_impact_active=is_impact_active,
                            last_manual_update_at=now,
                            site_id=site_id if tipo_nome == 'Site' else None,
                            circuit_id=circuit_id if tipo_nome in ['Backbone', 'Core'] else None,
                            device_id=device_id if tipo_nome in ['R.A.', 'Equipamento'] else None,
                            created_by=user,
                            assigned_to=user
                        )
                        
                        if affected_regions:
                            incident.affected_regions.set(affected_regions)
                        
                        # Histórico Inicial
                        UpdateIncident.objects.create(
                            incident=incident,
                            created_by=user,
                            status=incident.status,
                            is_impact_active=incident.is_impact_active,
                            comment="[SISTEMA] Abertura de incidente.",
                            impact_type=incident.impact_type,
                            impact_level=incident.impact_level,
                            expected_at=incident.expected_at,
                            time_elapsed=0
                        )
                    
                    return True
                except Exception as e:
                    return f"Erro ao salvar: {str(e)}"

            result = await save_new_incident()
            if isinstance(result, HttpResponse):
                return result
            
            if result is True:
                response = HttpResponse("""
                    <div class="text-center py-5 animate-fade-in">
                        <i class="bi bi-rocket-takeoff-fill text-success" style="font-size: 3rem;"></i>
                        <h5 class="mt-3 fw-bold text-success">Incidente Aberto com Sucesso!</h5>
                        <p class="text-muted" style="font-size: 11px;">Aguarde, atualizando dashboard...</p>
                        <script>
                            setTimeout(() => {
                                bootstrap.Modal.getInstance(document.getElementById('modalNovo')).hide();
                                window.location.reload(); 
                            }, 1500);
                        </script>
                    </div>
                """)
                response['HX-Trigger'] = 'incidenteCriado'
                return response
            
            return HttpResponse(f"<div class='alert alert-danger m-3'>{result}</div>")

        context = await get_context()
        return await sync_to_async(render)(request, 'users/partials/novo_incidente_modal.html', context)

    except Exception as e:
        error_msg = f"<strong>Erro:</strong> {str(e)}<br><small>{traceback.format_exc()}</small>"
        return HttpResponse(f"<div class='alert alert-danger m-3' style='font-size: 11px;'>{error_msg}</div>")

async def excluir_ultimo_update_ajax(request, update_id):
    """
    Exclui um registro de atualização específico (usado para resolver conflitos de timeline).
    """
    try:
        user = await request.auser()
        if not user.is_authenticated:
            return HttpResponse("Não autorizado", status=401)

        @sync_to_async
        def delete_update():
            update_obj = UpdateIncident.objects.select_related('incident').filter(id=update_id).first()
            if not update_obj:
                return "Registro não encontrado."
            
            incident = update_obj.incident
            # Só permite excluir se for o ÚLTIMO update do chamado
            last_update = UpdateIncident.objects.filter(incident=incident).order_by('-user_updated_at', '-created_at').first()
            
            if last_update and last_update.id != int(update_id):
                return "Só é possível excluir o último registro da timeline para evitar furos no histórico."

            with transaction.atomic():
                update_obj.delete()
                # Opcional: Reverter o status do incidente para o status do update anterior
                prev_update = UpdateIncident.objects.filter(incident=incident).order_by('-user_updated_at', '-created_at').first()
                if prev_update:
                    incident.status = prev_update.status
                    incident.is_impact_active = prev_update.is_impact_active
                    incident.impact_level = prev_update.impact_level
                    incident.impact_type = prev_update.impact_type
                    incident.expected_at = prev_update.expected_at
                    incident.save()
                else:
                    # Se não houver mais updates, volta ao estado inicial? (Raro)
                    pass

            return True

        result = await delete_update()
        if result is True:
            return HttpResponse("<div class='alert alert-success small p-2 mb-0'>Registro removido. Tente salvar novamente.</div>")
        else:
            return HttpResponse(f"<div class='alert alert-warning small p-2 mb-0'>{result}</div>")

    except Exception as e:
        return HttpResponse(f"Erro: {str(e)}", status=500)

async def ajustar_horario_update_ajax(request, update_id):
    """
    Ajusta apenas o horário (user_updated_at) de um registro de atualização.
    """
    try:
        user = await request.auser()
        if not user.is_authenticated:
            return HttpResponse("Não autorizado", status=401)

        new_time_str = request.POST.get('new_time')
        if not new_time_str:
            return HttpResponse("Horário não informado.", status=400)

        new_time = parse_datetime(new_time_str)
        if not new_time:
            return HttpResponse("Formato de data inválido.", status=400)
            
        if timezone.is_naive(new_time):
            new_time = timezone.make_aware(new_time)

        @sync_to_async
        def update_time():
            update_obj = UpdateIncident.objects.select_related('incident').filter(id=update_id).first()
            if not update_obj:
                return "Registro não encontrado."
            
            # Validação: O novo horário do registro anterior também não pode ser futuro
            if new_time > timezone.now():
                return "O novo horário não pode ser uma data futura."
            
            # Validação: Não pode ser anterior à abertura do chamado
            if new_time < update_obj.incident.occured_at:
                return "O horário não pode ser anterior à abertura do chamado."

            update_obj.user_updated_at = new_time
            update_obj.save()
            return True

        result = await update_time()
        if result is True:
            response = HttpResponse("<div class='alert alert-success small p-2 mb-0'>Horário do registro anterior atualizado! Tente salvar novamente.</div>")
            response['HX-Trigger'] = 'atualizacaoTimeline' # Dispara refresh da timeline local
            return response
        else:
            return HttpResponse(f"<div class='alert alert-warning small p-2 mb-0'>{result}</div>")

    except Exception as e:
        return HttpResponse(f"Erro: {str(e)}", status=500)

async def historico_incidente_ajax(request, protocolo):
    """
    Retorna apenas o partial da timeline de histórico de um incidente.
    """
    try:
        user = await request.auser()
        if not user.is_authenticated:
            return HttpResponse("Não autorizado", status=401)

        @sync_to_async
        def get_incident_history():
            incident = Incident.objects.prefetch_related(
                'updates__created_by', 
                'updates__status', 
                'updates__tags'
            ).filter(Q(protocol_number=protocolo) | Q(mk_protocol=protocolo)).first()
            return incident

        incident = await get_incident_history()
        if not incident:
            return HttpResponse("Incidente não encontrado.", status=404)

        return await sync_to_async(render)(request, 'users/partials/history_timeline.html', {'incident': incident})

    except Exception as e:
        return HttpResponse(f"Erro: {str(e)}", status=500)

# ==============================================================================
# [RBAC] GERENCIAMENTO DE ACESSOS E PERMISSÕES
# ==============================================================================

class AcessosView(LoginRequiredMixin, UserPassesTestMixin, TemplateView):
    template_name = 'users/acessos.html'
    
    def test_func(self):
        # Permite apenas superusuários ou quem tem a permissão específica
        return self.request.user.is_superuser or self.request.user.groups.filter(ui_permissions__slug='view_access_manager').exists()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from apps.users.models import UIPermission
        context['grupos'] = Group.objects.all().order_by('name')
        context['permissoes'] = UIPermission.objects.all().order_by('module', 'name')
        context['usuarios'] = User.objects.all().prefetch_related('groups').order_by('username')
        
        # [SEA PROTOCOL] Informações de Sequência do PostgreSQL
        if self.request.user.is_superuser or self.request.user.groups.filter(ui_permissions__slug='view_sequence_logs').exists():
            from django.db import connection
            with connection.cursor() as cursor:
                try:
                    cursor.execute("SELECT last_value, is_called FROM incident_protocol_seq")
                    row = cursor.fetchone()
                    context['seq_info'] = {'last_value': row[0], 'is_called': row[1]}
                except:
                    context['seq_info'] = {'error': 'Sequência não encontrada ou erro no banco.'}
        
        return context

async def api_toggle_permission(request):
    """
    Toggle de permissão de UI para um grupo via AJAX.
    """
    user = request.user
    if not user.is_superuser and not user.groups.filter(ui_permissions__slug='manage_permissions').exists():
        return JsonResponse({'success': False, 'error': 'Não autorizado'}, status=403)
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Método inválido'}, status=405)

    group_id = request.POST.get('group_id')
    perm_id = request.POST.get('perm_id')
    
    @sync_to_async
    def do_toggle():
        try:
            from apps.users.models import UIPermission
            group = Group.objects.get(id=group_id)
            perm = UIPermission.objects.get(id=perm_id)
            
            if perm in group.ui_permissions.all():
                group.ui_permissions.remove(perm)
                action = 'removed'
            else:
                group.ui_permissions.add(perm)
                action = 'added'
            return {'success': True, 'action': action}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    # Como estamos em uma view async, precisamos lidar com a transação se necessário
    # Mas aqui é um toggle simples.
    result = await do_toggle()
    return JsonResponse(result)

async def api_update_user_groups(request):
    """
    Atualiza os grupos de um usuário via AJAX.
    """
    if not request.user.is_superuser and not request.user.groups.filter(ui_permissions__slug='manage_permissions').exists():
        return JsonResponse({'success': False, 'error': 'Não autorizado'}, status=403)

    user_id = request.POST.get('user_id')
    group_ids = request.POST.getlist('group_ids[]') # Array do jQuery/Fetch
    
    @sync_to_async
    def do_update():
        try:
            with transaction.atomic():
                target_user = User.objects.get(id=user_id)
                target_user.groups.set(Group.objects.filter(id__in=group_ids))
                return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}
            
    result = await do_update()
    return JsonResponse(result)

async def api_promote_superuser(request):
    """
    Promove ou remove is_superuser com verificação de senha.
    """
    if not request.user.is_superuser:
        return JsonResponse({'success': False, 'error': 'Apenas superusuários podem promover outros.'}, status=403)

    user_id = request.POST.get('user_id')
    password = request.POST.get('password')
    action = request.POST.get('action') # 'promote' ou 'demote'

    if not request.user.check_password(password):
        return JsonResponse({'success': False, 'error': 'Senha incorreta.'}, status=401)

    @sync_to_async
    def do_action():
        try:
            target_user = User.objects.get(id=user_id)
            if action == 'promote':
                target_user.is_superuser = True
            else:
                target_user.is_superuser = False
            target_user.save() # O validador no model User impedirá a remoção do último superuser
            return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    result = await do_action()
    return JsonResponse(result)

async def api_manage_group(request):
    """
    Cria, edita ou exclui um grupo e associa permissões via AJAX.
    """
    if not request.user.is_superuser:
        return JsonResponse({'success': False, 'error': 'Acesso negado.'}, status=403)

    group_id = request.POST.get('group_id')
    name = request.POST.get('name')
    action = request.POST.get('action') # 'delete' ou None (save)
    perm_ids = request.POST.getlist('perm_ids[]')

    @sync_to_async
    def do_manage():
        from django.contrib.auth.models import Group
        from apps.users.models import UIPermission
        try:
            if action == 'delete':
                if not group_id: return {'success': False, 'error': 'ID não informado.'}
                group = Group.objects.get(id=group_id)
                # Proteção básica
                if group.name in ["N1", "N2", "Gestão"]:
                    return {'success': False, 'error': 'Não é permitido excluir grupos do sistema.'}
                group.delete()
                return {'success': True}
            
            # Save (Create/Update)
            if group_id:
                group = Group.objects.get(id=group_id)
                group.name = name
                group.save()
            else:
                group = Group.objects.create(name=name)
            
            # Atualiza permissões
            perms = UIPermission.objects.filter(id__in=perm_ids)
            group.ui_permissions.set(perms)
            
            return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    result = await do_manage()
    return JsonResponse(result)

async def api_manage_resource(request):
    """
    Cria, edita ou exclui um UIPermission via AJAX.
    """
    if not request.user.is_superuser:
        return JsonResponse({'success': False, 'error': 'Acesso negado.'}, status=403)

    res_id = request.POST.get('res_id')
    name = request.POST.get('name')
    slug = request.POST.get('slug')
    module = request.POST.get('module')
    description = request.POST.get('description', '')
    action = request.POST.get('action') # 'delete' ou None (save)

    @sync_to_async
    def do_manage():
        from apps.users.models import UIPermission
        try:
            if action == 'delete':
                if not res_id: return {'success': False, 'error': 'ID não informado.'}
                UIPermission.objects.get(id=res_id).delete()
                return {'success': True}
            
            # Save (Create/Update)
            if res_id:
                res = UIPermission.objects.get(id=res_id)
                res.name = name
                res.slug = slug
                res.module = module
                res.description = description
                res.save()
            else:
                UIPermission.objects.create(
                    name=name, slug=slug, module=module, description=description
                )
            return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    result = await do_manage()
    return JsonResponse(result)
