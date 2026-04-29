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
User = get_user_model()

class Command(BaseCommand):
    help = 'Sincroniza com o NETBOX'

    def handle(self, *args, **options):
        try:
            self.stdout.write("🔌 Sincronizando com Netbox (API)...")
            self._sync_netbox()
            self.stdout.write(self.style.SUCCESS("✨ Netbox sincronizado com sucesso!"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"💥 Erro crítico: {str(e)}"))
            import traceback
            self.stdout.write(traceback.format_exc())

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
                contract_energy = s.custom_fields.get('Conta_contrato')
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
                        'contract_energy': contract_energy,
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

