from django.shortcuts import render
from django.views.generic import TemplateView, DetailView, UpdateView
from django.contrib.auth.views import LoginView
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db.models import Count, Q
from django.utils import timezone
from django.core.cache import cache
from django.utils.dateparse import parse_datetime
from django.http import JsonResponse, HttpResponse
from django.urls import reverse, reverse_lazy
from asgiref.sync import sync_to_async
import traceback
import re

# Importação de todos os modelos necessários
from apps.incidents.models import (
    Incident, Status, UpdateIncident, 
    ImpactType, ImpactLevel, ClientType, SLA, IncidentType,
    RootCause, Symptom, DetectionSource
)
from apps.netbox.models import Region, Site, Circuit, Device
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
        ).select_related('status', 'incident_type', 'assigned_to').order_by('-occured_at')[:5]
        return context

class InformativosView(LoginRequiredMixin, PermissionRequiredMixin, TemplateView):
    template_name = 'users/informativos.html'
    permission_required = 'users.acessar_informativos'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['apply_preset'] = self.request.session.pop('first_access_after_login', False)
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
            ).filter(mk_protocol=protocolo).first()

            if not incident: return None

            now = timezone.now()
            end_time = incident.resolved_at or now

            # Cálculo de Cores da Previsão
            previsao_color = "#60c4b0"  
            if incident.expected_at:
                diff_seconds = (incident.expected_at - now).total_seconds()
                status_slug = incident.status.name.lower() if incident.status else ""
                
                if status_slug == "em andamento" and diff_seconds < 0:
                    previsao_color = "#dc3545"  
                elif 0 <= diff_seconds <= 1800:
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
            if incident.sla and incident.sla.name:
                digits = re.findall(r'\d+', str(incident.sla.name))
                if digits:
                    sla_hours = int(digits[0])

            afetacao_color = "#7da233" 
            if impact_td.total_seconds() > (sla_hours * 3600):
                afetacao_color = "#dc3545"

            def format_duration(td):
                total_m = int(td.total_seconds() // 60)
                if total_m <= 0: return "0min"
                d = total_m // 1440
                h = (total_m % 1440) // 60
                m = total_m % 60
                parts = []
                if d > 0: parts.append(f"{d}d")
                if h > 0: parts.append(f"{h}h")
                parts.append(f"{m}min")
                return " ".join(parts)

            # Designador e Nomes Planos
            tipo_nome = incident.incident_type.name if incident.incident_type else "N/D"
            if tipo_nome == 'Site':
                circuito_nome = incident.site.facility if (incident.site and incident.site.facility) else (incident.site.name if incident.site else "S/S")
            elif tipo_nome in ['Backbone', 'Core']:
                circuito_nome = incident.circuit.name if incident.circuit else "S/C"
            elif tipo_nome == 'R.A.':
                circuito_nome = incident.device.name if incident.device else "S/D"
            else:
                circuito_nome = "N/D"
                
            fornecedor_nome = incident.circuit.provider.name if incident.circuit and hasattr(incident.circuit, 'provider') and incident.circuit.provider else ""

            # [NOVO] Extracção de Impacto Físico
            impacto_tipo_nome = incident.impact_type.name if incident.impact_type else "N/D"
            impacto_nivel_nome = incident.impact_level.name if incident.impact_level else "N/D"

            # [NOVO] Histórico Otimizado
            # Iteramos de forma "reversed" (Decrescente) para a apresentação no Offcanvas
            safe_updates = []
            for u in reversed(updates_list):
                safe_updates.append({
                    'created_at': u.created_at,
                    'username': u.created_by.username if u.created_by else "Sistema",
                    
                    # Usa o novo campo 'comment', com fallback de segurança para 'technical_note'
                    'comment': getattr(u, 'comment', getattr(u, 'technical_note', "")),
                    'time_elapsed': getattr(u, 'time_elapsed', 0),
                    
                    # Flags booleanas para as Badges do UI
                    'is_opening': getattr(u, 'is_opening', False),
                    'is_closing': getattr(u, 'is_closing', False),
                    'is_new_status': getattr(u, 'is_new_status', False),
                    'is_new_expected_at': getattr(u, 'is_new_expected_at', False),
                    'is_new_impact_type': getattr(u, 'is_new_impact_type', False),
                    'is_new_impact_level': getattr(u, 'is_new_impact_level', False),
                    'is_new_comment': getattr(u, 'is_new_comment', False),
                })

            locais_list = [r.name for r in incident.affected_regions.all()]
            locais_afetados = ", ".join(locais_list) if locais_list else "Nenhum local mapeado"

            return {
                'incident': incident,
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
                'historico_updates': safe_updates
            }

        context_data = await process_incident_data()
        
        if not context_data:
            return HttpResponse(f"<div class='alert alert-danger m-3'>Protocolo {protocolo} não encontrado.</div>", status=404)
        
        return await sync_to_async(render)(request, 'users/partials/detalhe_offcanvas.html', context_data)

    except Exception as e:
        error_msg = f"<strong>Erro de Processamento:</strong> {str(e)}<br><small>{traceback.format_exc()}</small>"
        return HttpResponse(f"<div class='alert alert-danger m-3' style='font-size: 11px;'>{error_msg}</div>", status=200)


# --- [BOTÃO PLUS] View para Inserir Atualização Rápida ---
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
                client_type_id = request.POST.get('client_type_id')
                sla_id = request.POST.get('sla_id')
                
                # Novos campos
                assigned_to_id = request.POST.get('assigned_to_id')
                root_cause_id = request.POST.get('root_cause_id')
                note_text = request.POST.get('note', '').strip()
                rfo_text = request.POST.get('rfo', '').strip()
                
                is_impact_active = request.POST.get('is_impact_active') == 'True'
                
                # [AJUSTE] Modificado technical_note para comment de acordo com o modelo novo
                comment_text = request.POST.get('technical_note', '').strip()
                
                new_status = Status.objects.filter(id=status_id).first()
                
                # Atualização de relações paramétricas
                if impact_type_id: incident.impact_type_id = impact_type_id
                if impact_level_id: incident.impact_level_id = impact_level_id
                if client_type_id: incident.client_type_id = client_type_id
                if sla_id: incident.sla_id = sla_id
                
                # Lógica de Escalonamento
                if new_status and new_status.name.lower() == 'escalonado' and assigned_to_id:
                    incident.assigned_to_id = assigned_to_id
                
                # Lógica de Normalização (Root Cause, Note, RFO)
                if new_status and new_status.name.lower() == 'normalizado':
                    if root_cause_id: incident.root_cause_id = root_cause_id
                    if note_text: incident.note = note_text
                    if rfo_text: incident.rfo = rfo_text
                
                now = timezone.now()
                last_time = incident.last_history_update_at or incident.occured_at or now
                elapsed_minutes = max(0, int((now - last_time).total_seconds() / 60))
                
                # 1. Cria o registo de histórico usando as novas flags Booleanas e 'comment'
                UpdateIncident.objects.create(
                    incident=incident,
                    created_by=user,
                    status=new_status,
                    is_impact_active=is_impact_active,
                    comment=comment_text,
                    time_elapsed=elapsed_minutes,
                    
                    # Detecção básica de tipo de update a partir do POST
                    is_new_comment=bool(comment_text),
                    is_new_status=(incident.status != new_status),
                    is_closing=(new_status and new_status.name.lower() in ['normalizado', 'resolvido', 'encerrado'])
                )
                
                # 2. Atualiza o estado principal do Incidente
                incident.status = new_status
                incident.is_impact_active = is_impact_active
                incident.last_history_update_at = now
                
                # 3. Campos Administrativos / Normalização Automática
                if user.has_perm('incidents.can_edit_admin_fields') and new_status and new_status.name.lower() == 'normalizado':
                    occ_at = request.POST.get('occured_at')
                    res_at = request.POST.get('resolved_at')
                    if occ_at: incident.occured_at = parse_datetime(occ_at)
                    if res_at: incident.resolved_at = parse_datetime(res_at)
                elif new_status and new_status.name.lower() in ['normalizado', 'resolvido'] and not incident.resolved_at:
                    incident.resolved_at = now
                    
                incident.save()
                return True
                
            await save_update()
            
            # [HTMX] Retorna HTML de Sucesso. Sem Refresh. Aciona o listener do DataTables.
            response = HttpResponse("""
                <div class="text-center py-5 animate-fade-in">
                    <i class="bi bi-check-circle-fill text-success" style="font-size: 3rem;"></i>
                    <h5 class="mt-3 fw-bold text-success">Atualização Registada com Sucesso!</h5>
                    <p class="text-muted" style="font-size: 11px;">Pode fechar este painel. A tabela será atualizada.</p>
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
                'updates__created_by'
            ).filter(mk_protocol=protocolo).first()

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

            # Histórico ordenado
            updates_list = sorted(list(incident.updates.all()), key=lambda u: u.created_at, reverse=True)
            safe_updates = []
            for u in updates_list:
                safe_updates.append({
                    'created_at': u.created_at,
                    'username': u.created_by.username if u.created_by else "Sistema",
                    'comment': getattr(u, 'comment', getattr(u, 'technical_note', "")),
                    
                    # Flags
                    'is_opening': getattr(u, 'is_opening', False),
                    'is_closing': getattr(u, 'is_closing', False),
                    'is_new_status': getattr(u, 'is_new_status', False),
                    'is_new_expected_at': getattr(u, 'is_new_expected_at', False),
                    'is_new_impact_type': getattr(u, 'is_new_impact_type', False),
                    'is_new_impact_level': getattr(u, 'is_new_impact_level', False),
                    'is_new_comment': getattr(u, 'is_new_comment', False),
                })

            return {
                'incident': incident,
                'designador_nome': designador_nome,
                'lista_status': lista_status,
                'lista_tipos_impacto': lista_tipos_impacto,
                'lista_niveis_impacto': lista_niveis_impacto,
                'lista_tipos_cliente': lista_tipos_cliente,
                'lista_slas': lista_slas,
                'lista_causas_raiz': lista_causas_raiz,
                'lista_usuarios': lista_usuarios,
                'historico_updates': safe_updates
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
                incident = Incident.objects.filter(mk_protocol=protocolo).first()
                if not incident: return False
                
                # Resgate de Campos
                incident.incident_type_id = request.POST.get('incident_type_id')
                incident.detection_source_id = request.POST.get('detection_source_id') or None
                incident.reported_symptom_id = request.POST.get('reported_symptom_id') or None
                incident.sla_id = request.POST.get('sla_id')
                
                # Designador (Depende do Tipo)
                tipo = IncidentType.objects.get(id=incident.incident_type_id).name
                incident.site_id = request.POST.get('site_id') if tipo == 'Site' else None
                incident.circuit_id = request.POST.get('circuit_id') if tipo in ['Backbone', 'Core'] else None
                incident.device_id = request.POST.get('device_id') if tipo in ['R.A.', 'Equipamento'] else None
                
                # Datas
                occ_at = request.POST.get('occured_at')
                exp_at = request.POST.get('expected_at')
                if occ_at: incident.occured_at = parse_datetime(occ_at)
                if exp_at: incident.expected_at = parse_datetime(exp_at)
                
                # Texto
                incident.description = request.POST.get('description', '')
                
                # ManyToMany (Regiões)
                regioes = request.POST.getlist('affected_regions')
                if regioes: incident.affected_regions.set(regioes)
                
                incident.save()
                return True

            if await save_structural_edit():
                response = HttpResponse("""
                    <div class="text-center py-5 animate-fade-in">
                        <i class="bi bi-check-circle-fill text-warning" style="font-size: 3rem;"></i>
                        <h5 class="mt-3 fw-bold text-dark">Alterações Estruturais Salvas!</h5>
                        <p class="text-muted" style="font-size: 11px;">O chamado foi reparametrizado com sucesso.</p>
                    </div>
                """)
                response['HX-Trigger'] = 'atualizacaoConcluida'
                return response
            return HttpResponse("Erro ao salvar", status=400)

        # --- [GET] CARREGAMENTO DO FORMULÁRIO ---
        @sync_to_async
        def get_edit_context():
            incident = Incident.objects.select_related(
                'status', 'incident_type', 'site', 'circuit', 'device', 'detection_source', 'reported_symptom'
            ).filter(mk_protocol=protocolo).first()
            
            if not incident: return None
            
            return {
                'incident': incident,
                'lista_tipos': list(IncidentType.objects.all().order_by('name')),
                'lista_sintomas': list(Symptom.objects.all().order_by('name')),
                'lista_fontes': list(DetectionSource.objects.all().order_by('name')),
                'lista_slas': list(SLA.objects.all().order_by('id')),
                'lista_regioes': list(Region.objects.all().order_by('name')),
                
                # Listas de infra categorizadas (Apenas ATIVOS)
                'lista_sites': list(Site.objects.filter(netbox_status__slug='active').order_by('name')),
                
                'lista_circuitos_backbone': list(Circuit.objects.filter(
                    netbox_status__slug='active',
                    type__slug__in=['ce', 'rede-backbone-terceiros', 'rede-backbone-prpria']
                ).order_by('name')),
                
                'lista_circuitos_core': list(Circuit.objects.filter(
                    netbox_status__slug='active',
                    type__slug__in=['capacidade-ip', 'ptt']
                ).order_by('name')),
                
                # Para R.A., apenas Devices ATIVOS e com Role OLT
                'lista_devices': list(Device.objects.filter(
                    is_active=True,
                    role__slug='olt'
                ).order_by('name')),
            }

        context = await get_edit_context()
        if not context: return HttpResponse("Protocolo não encontrado", status=404)
        
        return await sync_to_async(render)(request, 'users/partials/editar_incidente_offcanvas.html', context)

    except Exception as e:
        return HttpResponse(f"Erro: {str(e)}", status=500)


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
            hoje = timezone.now().date()
            return Incident.objects.aggregate(
                em_andamento=Count('id', filter=Q(status__name__iexact='Em andamento')),
                normalizado=Count('id', filter=Q(status__name__iexact='Normalizado', resolved_at__date=hoje)),
                sem_afetacao=Count('id', filter=Q(status__name__iexact='Em andamento', is_impact_active=False)),
                com_afetacao=Count('id', filter=Q(status__name__iexact='Em andamento', is_impact_active=True))
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
        # [OTIMIZAÇÃO] Adicionado .only() para evitar carregar campos pesados (RFO, notas longas) 
        # que não são exibidos na listagem principal.
        incidents = Incident.objects.exclude(
            status__name__iexact='Excluido'
        ).select_related(
            'status', 'incident_type', 'circuit', 'site', 'device', 'assigned_to'
        ).only(
            'id', 'mk_protocol', 'occured_at', 'description', 'status__name', 
            'incident_type__name', 'is_impact_active', 'last_history_update_at',
            'site__name', 'site__facility', 'circuit__name', 'device__name',
            'assigned_to__username'
        ).order_by('-occured_at')
        
        data_list = []
        for inc in incidents:
            dt_occured_local = timezone.localtime(inc.occured_at) if inc.occured_at else None
            raw_updated = inc.last_history_update_at or inc.occured_at
            dt_updated_local = timezone.localtime(raw_updated) if raw_updated else None

            tipo_nome = inc.incident_type.name if inc.incident_type else ""
            designator = "N/D"

            if tipo_nome == 'Site':
                facility = inc.site.facility if inc.site and inc.site.facility else (inc.site.name if inc.site else "S/S")
                site_name = inc.site.name if inc.site else "S/S"
                designator = f"{facility} - {site_name}"
            elif tipo_nome in ['Backbone', 'Core']:
                designator = inc.circuit.name if inc.circuit else "S/C"
            elif tipo_nome == 'R.A.':
                designator = inc.device.name if inc.device else "S/D"

            data_list.append({
                'id': inc.id,
                'protocol': inc.mk_protocol or "S/P",
                'timestamp': dt_occured_local.strftime('%d/%m/%Y %H:%M') if dt_occured_local else "N/D",
                'timestamp_iso': dt_occured_local.isoformat() if dt_occured_local else None,
                'designator': designator,
                'description': inc.description[:100] + "..." if inc.description and len(inc.description) > 100 else (inc.description or ""),
                'status_name': inc.status.name if inc.status else "Desconhecido",
                'is_impact_active': inc.is_impact_active,
                'updated_at_iso': dt_updated_local.isoformat() if dt_updated_local else None, 
                'assigned_to': inc.assigned_to.username if inc.assigned_to else "Livre",
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
            from apps.incidents.models import Incident
            incident = Incident.objects.get(mk_protocol=protocolo)
            incident.assigned_to = user
            incident.save()
            return True
        except Exception as e:
            print(f"Erro ao resgatar: {e}")
            return False

    success = await do_rescue()
    return JsonResponse({'success': success})