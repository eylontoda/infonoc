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
    help = 'Migra usuários e incidentes do SQLite'

    def handle(self, *args, **options):
        sqlite_path = os.path.join(settings.BASE_DIR, 'backup_sqlite.db')
        if not os.path.exists(sqlite_path):
            self.stdout.write(self.style.ERROR(f"❌ Arquivo SQLite não encontrado em: {sqlite_path}"))
            return
        try:
            self.stdout.write("📦 Iniciando migração de Usuários...")
            self._migrate_users(sqlite_path)
            self.stdout.write("📦 Iniciando migração de Incidentes...")
            self._migrate_incidents(sqlite_path)
            self.stdout.write("history Iniciando migração de Histórico de Atualizações...")
            self._migrate_updates(sqlite_path)
            self.stdout.write(self.style.SUCCESS("✨ Migração do SQLite concluída!"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"💥 Erro crítico: {str(e)}"))
            import traceback
            self.stdout.write(traceback.format_exc())

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

            # [NOVO] Tradução para Incident Type (Cobre as variações de pontuação)
            incident_type_translation = {
                'R.A': 'R.A.',
                'Em Análise': 'Em análise',
                'R.A.': 'R.A.'
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
    
                # [NOVO] Lógica de impacto ativo baseada na coluna de impacto
                impacto_raw = str(row[10] or "").strip()
                is_impact_active_calc = (impacto_raw.lower() != "sem impacto")
    
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
                        
                        # [NOVO] Tradução e resgate seguro do incident_type
                        'incident_type': inc_type_map.get(
                            incident_type_translation.get(str(row[20]).strip(), str(row[20]).strip())
                        ) or next(iter(inc_type_map.values()), None),
                        
                        'sla': sla_map.get(str(row[22]) + 'H') or next(iter(sla_map.values()), None),
                        'impact_type': imp_type_map.get(row[10]) or next(iter(imp_type_map.values()), None),
                        'client_type': cli_type_map.get(row[16]) or next(iter(cli_type_map.values()), None),
                        'created_by': user_map.get(row[6]) or next(iter(user_map.values()), None),
                        'assigned_to': user_map.get(row[21]),
                        'rfo': row[19],
                        'note': row[7],
                        'is_impact_active': is_impact_active_calc,
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
            # [NOVO] Mapa com o estado de impacto inicial do incidente
            incident_impact_map = dict(Incident.objects.values_list('id', 'is_impact_active'))
            # [NOVO] Mapa com os status dos incidentes
            incident_status_map = dict(Incident.objects.values_list('id', 'status__name'))
            
            # [NOVO] Identifica o ID do último update para cada incidente
            last_updates_per_incident = {row[1]: row[0] for row in rows}
            last_update_ids_set = set(last_updates_per_incident.values())
            
            last_incident_id = None
            current_impact_state = False
            last_update_time = None
            count = 0
    
            for row in rows:
                update_id, incident_id, data_atualizacao, usuario_str, descricao, status_ant, status_novo = row
                
                # Ignorar caso o incidente não exista no banco
                if incident_id not in incident_impact_map:
                    continue
                    
                created_date = safe_date(data_atualizacao)
                desc_str = descricao or ""
                desc_lower = desc_str.lower()
    
                # --- Lógica de Tempo Decorrido e Limpeza de Estado ---
                time_elapsed_minutes = 0
                if incident_id != last_incident_id:
                    last_incident_id = incident_id
                    # [NOVO] O primeiro comentário herda o impacto ativo do incidente (informativo)
                    current_impact_state = incident_impact_map[incident_id]
                    last_update_time = created_date
                elif created_date and last_update_time:
                    time_elapsed_minutes = max(0, int((created_date - last_update_time).total_seconds() / 60))
                    last_update_time = created_date
    
                # --- Manutenção da variável de Impacto Ativo ---
                status_novo_lower = str(status_novo).strip().lower() if status_novo else ""
                
                if "afetação: iniciada" in desc_lower or status_novo_lower == "com afetação":
                    current_impact_state = True
                elif "afetação: encerrada" in desc_lower or status_novo_lower == "sem afetação":
                    current_impact_state = False
                    
                # [NOVO] Se for o último update, garante a consistência final
                is_last_update = (update_id in last_update_ids_set)
                is_incident_normalizado = (incident_status_map.get(incident_id) == 'Normalizado')
                
                if is_last_update:
                    # Se for normalizado e ainda estiver ativo, forçamos o encerramento no último update
                    if is_incident_normalizado and current_impact_state:
                        current_impact_state = False
                        slugs_to_add_extra = ['impact']
                    else:
                        slugs_to_add_extra = []
                    
                    # [CORREÇÃO] Sempre sincroniza o estado final do impacto para o incidente pai
                    # Isso garante que se um update do meio fechou a afetação, o incidente saiba disso
                    if not current_impact_state and incident_impact_map.get(incident_id, False):
                        Incident.objects.filter(id=incident_id).update(is_impact_active=False)
                else:
                    slugs_to_add_extra = []
    
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
                    
                slugs.extend(slugs_to_add_extra)
                # ----------------------------------------------------
    
                # Gravação no Django (Otimizada com Set)
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

