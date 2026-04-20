import os
import re
import sqlite3
import pynetbox
from django.conf import settings
from django.db import transaction, IntegrityError
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils.timezone import make_aware, is_naive
from django.utils.dateparse import parse_datetime

from apps.incidents.models import (
    Status, ImpactType, ImpactLevel, IncidentType, ClientType, UpdateIncident, 
    RootCause, SLA, Incident, DetectionSource, Symptom, UpdateTag
)
from apps.netbox.models import (
    Vendor, Role, SiteType, Region, 
    Site, DeviceType, Device, Provider, CircuitType, Circuit, Tenant, NetboxStatus
)

# Definição dinâmica do modelo de usuário
User = get_user_model()

class Command(BaseCommand):
    help = 'Semeia o banco ESTÁTICO, sincroniza com o NETBOX e migra usuários do SQLite'

    def handle(self, *args, **options):
        sqlite_path = os.path.join(settings.BASE_DIR, 'backup_sqlite.db')

        try:
            # BLOCO 1: Dados Estáticos (Rápido e Atômico)
            with transaction.atomic():
                self.stdout.write("🌱 [1/4] Semeando dados estáticos...")
                self._seed_static_data()
                self._seed_update_tags()

            # BLOCO 2: Sincronização Externa (FORA de transação - Chamadas API)
            self.stdout.write("🔌 [2/4] Sincronizando com Netbox (API)...")
            self._sync_netbox()

            # BLOCO 3: Migração de Incidentes
            if os.path.exists(sqlite_path):

                self.stdout.write("📦 [3/4] Iniciando migração de Usuários...")
                self._migrate_users(sqlite_path)

                self.stdout.write("📦 [3/4] Iniciando migração de Incidentes...")
                self._migrate_incidents(sqlite_path)

                # [NOVO] BLOCO 4: Migração de Updates (Histórico)
                self.stdout.write("history [4/4] Iniciando migração de Histórico de Atualizações...")
                self._migrate_updates(sqlite_path)
            else:
                self.stdout.write(self.style.ERROR(f"❌ Arquivo SQLite não encontrado em: {sqlite_path}"))
                return

            self.stdout.write(self.style.SUCCESS("✨ Processo de seed e migração concluído com sucesso!"))

        except Exception as e:
            # [NOVO] Log detalhado do erro para facilitar o debug
            self.stdout.write(self.style.ERROR(f"💥 Erro crítico durante o processo: {str(e)}"))
            import traceback
            self.stdout.write(traceback.format_exc())

    def _seed_static_data(self):
        """Popula tabelas estáticas com 100% dos valores manuais fornecidos"""
        self.stdout.write("  -> Criando Status e Tipos...")
        
        status = ['Em andamento', 'Pausado', 'Pendente terceiros', 'Escalonado', 'Em validação', 'Normalizado', 'Excluido']
        for name in status: Status.objects.get_or_create(name=name)

        impact_type = ['Total', 'Parcial', 'Intermitente', 'Nenhum']
        for name in impact_type: ImpactType.objects.get_or_create(name=name)

        impact_level = [
            'Nenhum cliente','Em análise','01 à 31 clientes', '32 à 100 clientes', '100 à 500 clientes', 
            '500 à 1000 clientes', '1000 à 2000 clientes', '2000 à 5000 clientes', 
            'Mais de 5000 clientes','Todos os clientes'
        ]
        for name in impact_level: ImpactLevel.objects.get_or_create(name=name)  

        incident_type = ['Backbone', 'R.A.', 'Site', 'Equipamento', 'Core', 'Em análise']
        for name in incident_type: IncidentType.objects.get_or_create(name=name)

        client_type = ['Nenhum', 'Em Análise', 'Banda Larga', 'Dedicado', 'Banda Larga e Dedicado']
        for name in client_type: ClientType.objects.get_or_create(name=name)

    def _seed_update_tags(self):
        """Popula as novas tags de histórico N:N"""
        self.stdout.write("  -> Criando Tags de Atualização...")
        
        tags = [
            # slug, name, color, icon
            ('is_new_comment', 'Nota Técnica', '#6c757d', 'bi-chat-left-text'),
            ('impact', 'Alteração de Afetação', '#fd7e14', 'bi-lightning'),
            ('expected_at', 'Nova Previsão', '#ffc107', 'bi-clock-history'),
            ('impact_level', 'Nível de Impacto', '#dc3545', 'bi-bar-chart-steps'),
            ('impact_type', 'Tipo de Impacto', '#d63384', 'bi-activity'),
        ]

        for slug, name, color, icon in tags:
            UpdateTag.objects.get_or_create(
                slug=slug,
                defaults={'name': name, 'color': color, 'icon': icon}
            )

        # LISTA INTEGRAL DE CAUSAS RAIZ (Sem reduções)
        root_causes = [
            "ATENUAÇÃO F.O - BACKBONE FORNECEDOR", "ATENUAÇÃO F.O - BACKBONE SEA TELECOM",
            "ATENUAÇÃO F.O - R.A SEA TELECOM", "ATENUAÇÃO F.O - CLIENTE",
            "EQUIPAMENTO - FORNECEDOR", "EQUIPAMENTO - SEA TELECOM",
            "FALHA CONFIGURAÇÃO - FORNECEDOR", "FALHA CONFIGURAÇÃO - SEA TELECOM",
            "FALHA ELÉTRICA - CLIENTE", "FALHA ELÉTRICA - FORNECEDOR",
            "FALHA ELÉTRICA - SEA TELECOM", "FALHA ELÉTRICA - CONCESSIONÁRIA",
            "INFRAESTRUTURA CLIENTE", "MANOBRA INDEVIDA - FORNECEDOR",
            "MANOBRA INDEVIDA - CONCESSIONÁRIA", "MANOBRA INDEVIDA - SEA TELECOM",
            "MANUTENÇÃO PREVENTIVA - FORNECEDOR", "MANUTENÇÃO PREVENTIVA - SEA TELECOM",
            "NÃO INFORMADO - FORNECEDOR", "NORMALIZADO SEM INTERVENÇÃO - FORNECEDOR",
            "NORMALIZADO SEM INTERVENÇÃO - SEA TELECOM", "ROMPIMENTO F.O - BACKBONE FORNECEDOR",
            "ROMPIMENTO F.O - BACKBONE SEA TELECOM", "ROMPIMENTO F.O - DROP SEA TELECOM",
            "ROMPIMENTO F.O - R.A FORNECEDOR", "ROMPIMENTO F.O - R.A SEA TELECOM",
            "SATURAÇÃO DE CIRCUITO IP", "TEMPERATURA ALTA - FORNECEDOR",
            "TEMPERATURA ALTA - SEA TELECOM", "VANDALISMO INFRAESTRUTURA - FORNECEDOR",
            "VANDALISMO INFRAESTRUTURA - SEA TELECOM", "SATURAÇÃO DE BACKBONE - SEA TELECOM",
            "SATURAÇÃO DE BACKBONE - FORNECEDOR", "ROMPIMENTO F.O - TROCA DE POSTE CONCESSIONÁRIA",
            "ROMPIMENTO F.O - SUPRESSÃO VEGETAÇÃO SEA TELECOM", 
            "ROMPIMENTO F.O - SUPRESSÃO VEGETAÇÃO CONCESSIONÁRIA",
            "ROMPIMENTO F.O - FOGO REDE CONCESSIONÁRIA", "ROMPIMENTO F.O - TROCA DE CABOS CONCESSIONÁRIA",
            "FALHA DE INTERCONEXÃO - OPERADORAS"
        ]
        for cause in root_causes: RootCause.objects.get_or_create(name=cause) 

        sla_values = ['1h', '4h', '6h', '8h', '12h', '24h', '48h', 'Sem SLA']
        for name in sla_values: SLA.objects.get_or_create(name=name)
        
        site_type = ['INDOOR', 'OUTDOOR', '---']
        for st in site_type: SiteType.objects.get_or_create(name=st)

        detection_sources = [
            'Monitoramento Proativo (Zabbix/Grafana)',
            'Chamado do Cliente (Reativo)',
            'Aviso de Fornecedor / Operadora',
            'Constatação Interna / Equipe Técnica',
            'Não Informado'  # Fundamental para os dados do SQLite antigo
        ]
        for ds in detection_sources: 
            DetectionSource.objects.get_or_create(name=ds)

        # [NOVO] Sintomas Reportados (Symptom)
        # Mesclamos as strings do seu banco antigo com nomenclaturas modernas
        symptoms = [
            'Indisponibilidade',
            'Degradação',
            'Latência Elevada',
            'Intermitência',
            'Falha Elétrica',
            'Falha de Equipamento',
            'Temperatura Alta',
            'Manutenção Programada',
            'Sintoma Desconhecido'  # Fallback de segurança
        ]
        for sym in symptoms: 
            Symptom.objects.get_or_create(name=sym)
    def _get_netbox_client(self):
        if not settings.NETBOX_API_URL or not settings.NETBOX_API_TOKEN:
            self.stdout.write(self.style.ERROR("❌ Netbox URL/Token não configurados"))
            return None
        return pynetbox.api(settings.NETBOX_API_URL, token=settings.NETBOX_API_TOKEN)

    def _sync_netbox(self):
        nb = self._get_netbox_client()
        if not nb: return
        self.stdout.write(self.style.MIGRATE_HEADING("🚀 Iniciando Revisão Massiva do Netbox..."))
        self._sync_simple_table(nb.dcim.manufacturers, Vendor, "Fabricantes")
        self._sync_simple_table(nb.dcim.regions, Region, "Regiões")
        self._sync_simple_table(nb.tenancy.tenants, Tenant, "Fornecedores")
        self._sync_netbox_status(nb)
        self._sync_providers(nb)
        self._sync_roles(nb)
        self._sync_circuit_types(nb)
        self._sync_device_types(nb)
        self._sync_sites(nb)
        self._sync_devices(nb)
        self._sync_circuits(nb)

    # Métodos de Sincronização Netbox (Mantidos conforme lógica anterior)
    def _sync_simple_table(self, endpoint, model, label):
        self.stdout.write(f"  -> Sincronizando {label}...")
        for item in endpoint.all():
            model.objects.update_or_create(netbox_id=item.id, defaults={'name': item.name})

    def _sync_netbox_status(self, nb):
        self.stdout.write("  -> Sincronizando Netbox Status...")
        common = [{'n': 'Active', 's': 'active'}, {'n': 'Planned', 's': 'planned'}, {'n': 'Failed', 's': 'failed'}]
        for st in common:
            NetboxStatus.objects.update_or_create(slug=st['s'], defaults={'name': st['n']})

    def _sync_providers(self, nb):
        self.stdout.write("  -> Sincronizando Provedores...")
        
        # [NOVO] Criação do Provedor de Fallback (Segurança para registros órfãos)
        Provider.objects.update_or_create(
            netbox_id=0,
            defaults={
                'name': 'SEM_PROVEDOR',
                'slug': 'sem-provedor'
            }
        )

        # Sincronização dos dados reais do Netbox
        for item in nb.circuits.providers.all():
            Provider.objects.update_or_create(
                netbox_id=item.id,
                defaults={
                    'name': item.name,
                    'slug': item.slug
                }
            )

    def _sync_roles(self, nb):
        self.stdout.write("  -> Sincronizando Roles...")
        slugs = ['p', 'olt', 'core-switch', 'router', 'bras', 'bng', 'cdn', 'access-switch']
        for r in nb.dcim.device_roles.filter(slug=slugs):
            Role.objects.update_or_create(netbox_id=r.id, defaults={'name': r.name, 'slug': r.slug})

    def _sync_circuit_types(self, nb):
        self.stdout.write("  -> Sincronizando Circuit Types...")
        slugs = ['ce', 'rede-backbone-terceiros', 'rede-backbone-prpria', 'capacidade-ip', 'ptt']
        for ct in nb.circuits.circuit_types.filter(slug=slugs):
            CircuitType.objects.update_or_create(
                netbox_id=ct.id, 
                defaults={'name': ct.name, 'slug': ct.slug, 'description': getattr(ct, 'description', '')[:100]}
            )

    def _sync_device_types(self, nb):
        self.stdout.write("  -> Sincronizando Device Types...")
        for dt in nb.dcim.device_types.all():
            v = Vendor.objects.filter(netbox_id=dt.manufacturer.id).first()
            if v: DeviceType.objects.update_or_create(netbox_id=dt.id, defaults={'name': dt.model, 'vendor': v})

    def _sync_sites(self, nb):
        self.stdout.write("  -> Sincronizando Sites...")
        
        # Criar ou obter a Região de Fallback
        fallback_region, _ = Region.objects.get_or_create(
            name="SEM REGIÃO / NÃO DEFINIDA",
            defaults={'netbox_id': 0}
        )
        
        # [NOVO] Garante que o SiteType padrão exista para evitar erro no get
        default_st, _ = SiteType.objects.get_or_create(name="---")

        for s in nb.dcim.sites.all():
            # Tenta buscar a região vinda do Netbox
            region_id = s.region.id if s.region else None
            region = Region.objects.filter(netbox_id=region_id).first() if region_id else fallback_region
            
            if not region:
                region = fallback_region

            # [NOVO] Coleta do facility com normalização
            facility_val = (getattr(s, 'facility', "N/A") or "N/A").upper()

            # [NOVO] Lógica para o campo Tenant
            tenant_obj = None
            if s.tenant:
                # [NOVO] Busca ou cria o Tenant local baseado no Netbox ID
                tenant_obj, _ = Tenant.objects.update_or_create(
                    netbox_id=s.tenant.id,
                    defaults={'name': s.tenant.name}
                )

            # Coleta de campos customizados e status
            abrigo = s.custom_fields.get('abrigo')
            st_type = SiteType.objects.filter(name=abrigo).first() or default_st
            
            # [NOVO] Mapeia o status do Netbox para o modelo local
            nb_st, _ = NetboxStatus.objects.get_or_create(
                slug=s.status.value, 
                defaults={'name': s.status.label}
            )
            
            # [NOVO] Executa o update_or_create com a nova FK tenant
            Site.objects.update_or_create(
                netbox_id=s.id,
                defaults={
                    'name': s.name,
                    'facility': facility_val,
                    'region': region,
                    'coordinate': f"{s.latitude},{s.longitude}" if s.latitude and s.longitude else None,
                    'physical_address': getattr(s, 'physical_address', ''),
                    'site_type': st_type,
                    'netbox_status': nb_st,
                    'tenant': tenant_obj, # [NOVO] Injeção da FK Tenant
                }
            )

    def _sync_devices(self, nb):

        self.stdout.write("  -> Sincronizando Devices...")
        
        # Cache para performance O(n)
        try:
            site_map = {s.netbox_id: s for s in Site.objects.all()}
            type_map = {t.netbox_id: t for t in DeviceType.objects.all()}
            role_map = {r.netbox_id: r for r in Role.objects.all()}
            vendor_map = {v.netbox_id: v for v in Vendor.objects.all()}
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"💥 Erro ao carregar cache de mapas: {e}"))
            return

        role_ids = list(role_map.keys())
        
        success_count = 0
        error_count = 0

        # Filtramos os dispositivos no Netbox pelos papéis (roles) monitorados localmente
        for d in nb.dcim.devices.filter(role_id=role_ids):
            try:
                site = site_map.get(d.site.id)
                dtype = type_map.get(d.device_type.id)
                
                # Resolução do Status do Netbox
                nb_st, _ = NetboxStatus.objects.get_or_create(
                    slug=d.status.value, 
                    defaults={'name': d.status.label}
                )
                
                # Lógica booleana estrita: apenas o slug 'active' define o campo como True
                is_currently_active = (nb_st.slug == 'active')

                if not site or not dtype:
                    continue

                device_name = d.name or f"NB-ID-{d.id}"

                # PREVENÇÃO DE CONFLITO PARA UNIQUE CONSTRAINT PARCIAL
                # Garante que apenas um registro com o mesmo Nome/Site esteja is_active=True
                if is_currently_active:
                    conflict = Device.objects.filter(
                        name=device_name, 
                        site=site, 
                        is_active=True
                    ).exclude(netbox_id=d.id).first()

                    if conflict:
                        self.stdout.write(self.style.WARNING(f"    ! Conflito detectado: Desativando duplicata local para {device_name}"))
                        conflict.is_active = False
                        conflict.save()

                # Persistência usando netbox_id como âncora principal
                Device.objects.update_or_create(
                    netbox_id=d.id,
                    defaults={
                        'name': device_name,
                        'site': site,
                        'device_type': dtype,
                        'role': role_map.get(d.device_role.id),
                        'vendor': vendor_map.get(d.device_type.manufacturer.id) if hasattr(d.device_type, 'manufacturer') else None,
                        'netbox_status': nb_st,
                        'is_active': is_currently_active,
                        'primary_ip': d.primary_ip4.address.split('/')[0] if d.primary_ip4 else None,
                    }
                )
                
                success_count += 1
                if success_count % 50 == 0:
                    self.stdout.write(f"    ⏳ Processados {success_count} devices...")

            except Exception as e:
                device_label = d.name if hasattr(d, 'name') else f"ID:{d.id}"
                self.stdout.write(self.style.ERROR(f"    ❌ Erro em {device_label}: {str(e)}"))
                error_count += 1

        self.stdout.write(self.style.SUCCESS(f"  ✅ Sincronizado: {success_count} dispositivos."))

    def _sync_circuits(self, nb):
        self.stdout.write("  -> Sincronizando Circuitos...")

        # [NOVO] Cache de Provedores, Sites e Tipos para performance O(n)
        provider_map = {p.netbox_id: p for p in Provider.objects.all()}
        site_map = {s.netbox_id: s for s in Site.objects.all()}
        type_map = {t.netbox_id: t for t in CircuitType.objects.all()}
        
        # 1. Recupera o Provedor de Fallback
        fallback_provider = Provider.objects.filter(netbox_id=0).first() or Provider.objects.first()

        # 2. Criação do Circuito de Fallback (Segurança para o NOC)
        Circuit.objects.update_or_create(
            netbox_id=0,
            defaults={
                'name': 'CIRCUITO-DESCONHECIDO',
                'type': CircuitType.objects.first(),
                'provider': fallback_provider,
                'netbox_status': NetboxStatus.objects.first() 
            }
        )

        # 3. Sincronização dos dados reais do Netbox
        circuit_type_ids = list(type_map.keys())
        
        for c in nb.circuits.circuits.filter(type_id=circuit_type_ids):
            prov = provider_map.get(c.provider.id, fallback_provider)
            
            # Mapeamento do Status vindo do Netbox
            nb_st, _ = NetboxStatus.objects.get_or_create(
                slug=c.status.value, 
                defaults={'name': c.status.label}
            )

            # Resolução das terminações A e Z para os Sites correspondentes
            site_a_obj = None
            if c.termination_a and c.termination_a.site:
                site_a_obj = site_map.get(c.termination_a.site.id)

            site_z_obj = None
            if c.termination_z and c.termination_z.site:
                site_z_obj = site_map.get(c.termination_z.site.id)

            # [NOVO] Persistência: O campo 'name' recebe obrigatoriamente o CID do Netbox
            Circuit.objects.update_or_create(
                netbox_id=c.id, # ID numérico do Netbox como chave única
                defaults={
                    'name': c.cid.strip() if c.cid else f"ID-{c.id}", # [NOVO] CID mapeado para name
                    'type': type_map.get(c.type.id),
                    'provider': prov, 
                    'netbox_status': nb_st,
                    'site_a': site_a_obj,
                    'site_z': site_z_obj,
                    'external_identifier': c.custom_fields.get('designacao_operadora') if hasattr(c, 'custom_fields') else None
                }
            )
    def _migrate_users(self, sqlite_db_path):
        self.stdout.write("[SQLite] Sincronizando Usuários...")
        db_path = os.path.join(settings.BASE_DIR, 'backup_sqlite.db')
        
        if not os.path.exists(db_path):
            self.stdout.write(self.style.ERROR(f"     ❌ Arquivo não encontrado: {db_path}"))
            return

        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            # [NOVO] Adicionado 'password' ao SELECT
            cursor.execute("SELECT username, password, online, ultimo_acesso FROM usuario")
            
            for row in cursor.fetchall():
                aware_date = None
                if row['ultimo_acesso']:
                    dt = parse_datetime(row['ultimo_acesso'])
                    if dt: aware_date = make_aware(dt) if is_naive(dt) else dt

                # [NOVO] Lógica de privilégios para o administrador
                is_admin = (row['username'] == "superadmin")

                # 1. Criamos ou buscamos o usuário com as flags corretas
                user, created = User.objects.update_or_create(
                    username=row['username'],
                    defaults={
                        'is_online': bool(row['online']), 
                        'last_access': aware_date, 
                        'is_active': True,
                        'is_superuser': is_admin, # [NOVO] Define se é superusuário
                        'is_staff': is_admin,     # [NOVO] Permite acesso ao /admin/
                    }
                )

                # 2. Injetamos o hash original do Flask/Werkzeug
                if row['password']:
                    user.password = row['password']
                    user.save()
                    
                if created:
                    status = "Superusuário" if is_admin else "Usuário"
                
            conn.close()
            self.stdout.write(self.style.SUCCESS("     ✅ Usuários migrados com sucesso."))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"     💥 Erro na migração: {e}"))




    def _parse_local_afetado(self, raw_string):
        """
        Retorno padronizado: (Lista de Regiões, Infra Encontrada, Booleano Global)
        """
        ignored_locals = {'--', '---', '----', 'NENHUMA', 'OESTE'}
        # [AJUSTE] Palavras-chave que ativam o modo "Todos os clientes"
        global_keywords = {'TODAS', 'TODOS', 'TODAS-', 'GERAL', 'DIVERSAS'}
        
        region_translation = {
            'SANTA IZABEL': 'SANTA ISABEL DO PARÁ',
            'SANA IZABEL DO PARÁ': 'SANTA ISABEL DO PARÁ',
            'SANTA IZABEL DO PARÁ': 'SANTA ISABEL DO PARÁ',
            'BELÉM CIDADE NOVA': 'ANANINDEUA', 
            'ANANINDEUA CIDADE NOVA': 'ANANINDEUA',
            'COQUEIRO - BELÉM': 'ANANINDEUA',
            'BELÉM CASTANHEIRA': 'BELÉM',
            'CASTANHAL TREVO MACAPAZINHO': 'CASTANHAL',
            'SAUDADE - CASTANHAL': 'CASTANHAL',
            'IMPERIAL - CASTANHAL': 'CASTANHAL',
            'CASTANHAL (JADERLÂNDIA)': 'CASTANHAL',
            'CASTANHAL (SDD)': 'CASTANHAL',
            'CASTANHAL- MAXIMINO': 'CASTANHAL',
            'SALINAS MAÇARICO': 'SALINÓPOLIS',
            'SALINAS': 'SALINÓPOLIS',
            'B101 - BELTERRA KM 101': 'BELTERRA',
            'BELTERRA KM 101': 'BELTERRA',
            'BELTERRA CARIOCA': 'BELTERRA',
            'ITUPIRANGA CAJAZEIRAS': 'ITUPIRANGA',
            'CAJAZEIRAS': 'ITUPIRANGA', 
            'MARUDÁ': 'MARAPANIM', 
        }

        if not raw_string:
            return [], None, False
        
        text = str(raw_string).strip().upper()
        text = text.replace('"', '').replace('\t', '').strip()

        if not text or text in ignored_locals:
            return [], None, False

        # [NOVO] Se for global, retornamos a flag True para processamento posterior
        if text in global_keywords:
            return [], None, True

        # Equipamento/Circuito
        if '#' in text or text.startswith('BR-PA-'):
            return [], text.strip(), False

        # Quebra de cidades
        parts = re.split(r'\s+<>\s+|\s+X\s+|\s+-\s+', text)
        regions_found = []
        for part in parts:
            part_clean = part.strip()
            if not part_clean: continue
            final_name = region_translation.get(part_clean, part_clean)
            regions_found.append(final_name)
            
        return regions_found, None, False

    def _migrate_incidents(self, sqlite_db_path):
        self.stdout.write("[SQLite] Sincronizando Incidentes...")

        def safe_date(dt_val):
            if not dt_val: return None
            dt_parsed = parse_datetime(str(dt_val))
            if dt_parsed and is_naive(dt_parsed):
                return make_aware(dt_parsed)
            return dt_parsed

        conn = sqlite3.connect(sqlite_db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM informativo")
        rows = cursor.fetchall()

        # Cache de mapas
        user_map = {u.username: u for u in User.objects.all()}
        status_map = {s.name: s for s in Status.objects.all()}
        inc_type_map = {i.name: i for i in IncidentType.objects.all()}
        sla_map = {s.name: s for s in SLA.objects.all()}
        imp_type_map = {i.name: i for i in ImpactType.objects.all()}
        imp_lvl_map = {i.name: i for i in ImpactLevel.objects.all()}
        cli_type_map = {c.name: c for c in ClientType.objects.all()}
        region_map = {r.name.upper(): r for r in Region.objects.all()}
        symptom_map = {s.name: s for s in Symptom.objects.all()}
        
        # [NOVO] Mapas para resolver a infraestrutura baseada no campo designador
        circuit_map = {c.name.strip().upper(): c for c in Circuit.objects.all() if c.name}
        device_map = {d.name.strip().upper(): d for d in Device.objects.all() if d.name}
        
        site_map_flex = {}
        for s in Site.objects.all():
            if s.name:
                site_map_flex[s.name.strip().upper()] = s
            if s.facility:
                site_map_flex[s.facility.strip().upper()] = s
            if s.name and s.facility:
                site_map_flex[f"{s.name.strip()} - {s.facility.strip()}".upper()] = s
        
        
        impact_level_translation = {
            '1-31': '01 à 31 clientes',
            '32-99': '32 à 100 clientes',
            '100-499': '100 à 500 clientes',
            '500-999': '500 à 1000 clientes',
            '1000-1999': '1000 à 2000 clientes',
            '2000-4999': '2000 à 5000 clientes',
            '5000+': 'Mais de 5000 clientes',
            'Em Análise': 'Em análise',
            'Nenhum': 'Nenhum cliente',
            'Todos': 'Todos os clientes' # [NOVO] Tradução adicional
        }

        symptom_translation = {
            'Degradação': 'Degradação',
            'Falha Elétrica': 'Falha Elétrica',
            'Falha Equipamento': 'Falha de Equipamento',
            'Indisponibilidade': 'Indisponibilidade',
            'Intermitência': 'Intermitência',
            'Latência Elevada': 'Latência Elevada',
            'Manutenção': 'Manutenção Programada',
            'Temperatura Alta': 'Temperatura Alta',
        }

        # Valores padrão
        default_imp_lvl = imp_lvl_map.get("Nenhum cliente")

        count = 0
        for row in rows:
            old_id = row[0]
            local_afetado_raw = row[9]
            impact_level_raw = row[12]

            # Unpacking recebe os 3 valores
            region_names, infra_escondida, is_global = self._parse_local_afetado(local_afetado_raw)

            # [NOVO] Lógica solicitada: Se for global, o nível de impacto é "Todos os clientes"
            if is_global:
                impact_level_obj = imp_lvl_map.get('Todos os clientes', default_imp_lvl)
            else:
                impact_level_traduzido = impact_level_translation.get(impact_level_raw, impact_level_raw)
                impact_level_obj = imp_lvl_map.get(impact_level_traduzido, default_imp_lvl)

            # Tradução de sintoma (coluna 15)
            symptom_raw = str(row[15] or "").strip()
            symptom_translated = symptom_translation.get(symptom_raw, 'Sintoma Desconhecido')
            symptom_obj = symptom_map.get(symptom_translated)

            # Tradução de status
            status_raw = str(row[3]).strip().lower()
            if status_raw in ['resolvido', 'normalizado']:
                status_obj = status_map.get('Normalizado')
            elif status_raw in ['em andamento']:
                status_obj = status_map.get('Em andamento')
            else:
                status_obj = next(iter(status_map.values()), None)

            # [NOVO] Resolução baseada no conteúdo do campo "designador" (row[14])
            designador_raw = str(row[14] or "").strip()
            
            circuit_obj = None
            site_obj = None
            device_obj = None

            if designador_raw:
                designador_upper = designador_raw.upper()
                
                # 2 - Se o campo começar com "BR-", é um equipamento
                if designador_upper.startswith("BR-"):
                    device_obj = device_map.get(designador_upper)
                
                # 3 - Se o campo tiver "#" em um dos 5 primeiros caracteres, procure em Circuits
                elif "#" in designador_upper[:5]:
                    circuit_obj = circuit_map.get(designador_upper)
                
                # 1 - Se for a cidade por extenso ou "facility - name", associe ao Site
                else:
                    site_obj = site_map_flex.get(designador_upper)

            # [NOVO] Persistência com a regra de impacto global
            inc_obj, created = Incident.objects.update_or_create(
                id=old_id,
                defaults={
                    'mk_protocol': row[1] or "",
                    'impact_level': impact_level_obj,
                    'description': row[2] or "",
                    'occured_at': safe_date(row[17]) or parse_datetime("2023-01-01T00:00:00Z"),
                    'expected_at': safe_date(row[18]),
                    'resolved_at': safe_date(row[11]),
                    'status': status_obj,
                    'reported_symptom': symptom_obj,
                    'incident_type': inc_type_map.get(row[20]) or next(iter(inc_type_map.values()), None),
                    'sla': sla_map.get(str(row[22]) + 'H') or next(iter(sla_map.values()), None),
                    'impact_type': imp_type_map.get(row[10]) or next(iter(imp_type_map.values()), None),
                    'client_type': cli_type_map.get(row[16]) or next(iter(cli_type_map.values()), None),
                    'created_by': user_map.get(row[6]) or next(iter(user_map.values()), None),
                    'assigned_to': user_map.get(row[21]),
                    'rfo': row[19],
                    'note': row[7],
                    'is_impact_active': bool(row[23]),
                    'circuit': circuit_obj,
                    'site': site_obj,
                    'device': device_obj,
                }
            )

            # [NOVO] Só mapeia cidades se NÃO for global (regra solicitada)
            if not is_global and region_names:
                regions_to_add = [region_map.get(r.upper()) for r in region_names if region_map.get(r.upper())]
                if regions_to_add:
                    inc_obj.affected_regions.set(regions_to_add)
            elif is_global:
                # [NOVO] Limpa quaisquer regiões se por acaso o incidente tiver sido alterado para global
                inc_obj.affected_regions.clear()

            count += 1
            if count % 100 == 0:
                self.stdout.write(f"    ⏳ {count} processados...")

        conn.close()
        self.stdout.write(self.style.SUCCESS(f"✅ {count} incidentes migrados."))


    def _migrate_updates(self, sqlite_db_path):
        self.stdout.write("[SQLite] Sincronizando Histórico de Atualizações com Lógica Booleana...")

        def safe_date(dt_val):
            if not dt_val: return None
            try:
                from django.utils.dateparse import parse_datetime
                from django.utils.timezone import is_naive, make_aware
                dt_parsed = parse_datetime(str(dt_val))
                if dt_parsed and is_naive(dt_parsed):
                    return make_aware(dt_parsed)
                return dt_parsed
            except:
                return None

        try:
            import sqlite3
            conn = sqlite3.connect(sqlite_db_path)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, informativo_id, data_atualizacao, usuario, descricao, status_anterior, status_novo 
                FROM historico_atualizacao
                ORDER BY informativo_id ASC, data_atualizacao ASC
            """)
            rows = cursor.fetchall()
        except sqlite3.Error as e:
            self.stdout.write(self.style.ERROR(f"💥 Erro SQLite: {e}"))
            return

        from apps.incidents.models import ImpactLevel, Status, UpdateIncident
        from django.contrib.auth import get_user_model
        User = get_user_model()
        
        # Caches de Alta Performance
        user_map = {u.username: u for u in User.objects.all()}
        status_map = {s.name.lower(): s for s in Status.objects.all()}
        tag_map = {t.slug: t for t in UpdateTag.objects.all()}
        valid_incident_ids = set(Incident.objects.values_list('id', flat=True))
        
        last_incident_id = None
        current_impact_state = False
        last_update_time = None
        count = 0

        for row in rows:
            update_id, incident_id, data_atualizacao, usuario_str, descricao, status_ant, status_novo = row
            
            created_date = safe_date(data_atualizacao)
            desc_str = descricao or ""
            desc_lower = desc_str.lower()

            # --- Lógica de Tempo Decorrido e Limpeza de Estado ---
            time_elapsed_minutes = 0
            if incident_id != last_incident_id:
                last_incident_id = incident_id
                current_impact_state = False
                last_update_time = created_date
            elif created_date and last_update_time:
                time_elapsed_minutes = max(0, int((created_date - last_update_time).total_seconds() / 60))
                last_update_time = created_date

            # --- Manutenção da variável de Impacto Ativo ---
            if "afetação: iniciada" in desc_lower:
                current_impact_state = True
            elif "afetação: encerrada" in desc_lower:
                current_impact_state = False

            # --- Resolução do Status Objeto ---
            status_obj = None
            if status_novo:
                status_obj = status_map.get(str(status_novo).lower().strip())
            if not status_obj and status_map:
                status_obj = list(status_map.values())[0]

            # ----------------------------------------------------
            # [NOVO] Motor de Inferência de Tags N:N (Simplificado)
            # ----------------------------------------------------
            slugs = []
            
            # Comentário manual
            if len(desc_str.strip()) > 0:
                slugs.append('is_new_comment')
            
            # Previsão
            if "nova previsão:" in desc_lower:
                slugs.append('expected_at')
            
            # Afetação
            if ("afetação: iniciada" in desc_lower) or ("afetação: encerrada" in desc_lower):
                slugs.append('impact')
                slugs.append('impact_level')
                slugs.append('impact_type')
            # ----------------------------------------------------

            # Gravação no Django (Otimizada com Set)
            if incident_id not in valid_incident_ids:
                continue

            obj, created = UpdateIncident.objects.update_or_create(
                id=update_id,
                defaults={
                    'incident_id': incident_id,
                    'created_by': user_map.get(usuario_str, user_map.get("superadmin")),
                    
                    # Conteúdo Base
                    'status': status_obj,
                    'is_impact_active': current_impact_state,
                    'comment': desc_str or "Sem descrição.",
                    'time_elapsed': time_elapsed_minutes,
                }
            )

            # Atribuição das Tags via Cache
            if slugs:
                tags_to_add = [tag_map[s] for s in slugs if s in tag_map]
                if tags_to_add:
                    obj.tags.set(tags_to_add)

            # Forçar as datas via SQL para ignorar o auto_now_add
            if created_date:
                UpdateIncident.objects.filter(id=obj.id).update(created_at=created_date)

            count += 1
            if count % 100 == 0:
                self.stdout.write(f"    ⏳ Processados {count} updates...")

        conn.close()
        self.stdout.write(self.style.SUCCESS(f"  ✅ Concluído! {count} históricos sincronizados com sucesso."))