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
    help = 'Semeia o banco ESTÁTICO'

    def handle(self, *args, **options):
        try:
            with transaction.atomic():
                self.stdout.write("🌱 Semeando dados estáticos...")
                self._seed_static_data()
                self._seed_update_tags()
            self.stdout.write(self.style.SUCCESS("✨ Dados estáticos criados com sucesso!"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"💥 Erro crítico: {str(e)}"))
            import traceback
            self.stdout.write(traceback.format_exc())

    def _seed_static_data(self):
            """Popula tabelas estáticas com 100% dos valores manuais fornecidos"""
            self.stdout.write("  -> Criando Status e Tipos...")
            
            status = ['Em abertura', 'Em andamento', 'Pausado', 'Pendente terceiros', 'Pendente resgate', 'Escalonado', 'Em validação', 'Normalizado', 'Excluido']
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
                ('stopped_at', 'Pausa Programada', '#6f42c1', 'bi-pause-circle'),
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

