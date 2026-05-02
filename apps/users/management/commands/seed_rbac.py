from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group
from apps.users.models import UIPermission

class Command(BaseCommand):
    help = 'Semeia as permissões de interface iniciais (RBAC)'

    def handle(self, *args, **options):
        permissions = [
            # Incidentes
            {'name': 'Ver Lista de Incidentes', 'slug': 'view_incident_list', 'module': 'Incidentes', 'desc': 'Permite visualizar as tabelas de incidentes.'},
            {'name': 'Editar Informações', 'slug': 'edit_incident', 'module': 'Incidentes', 'desc': 'Permite abrir o modal de edição de incidente.'},
            {'name': 'Fechar Chamado', 'slug': 'btn_close_incident', 'module': 'Incidentes', 'desc': 'Permite normalizar/encerrar um incidente.'},
            {'name': 'Excluir Incidente', 'slug': 'delete_incident', 'module': 'Incidentes', 'desc': 'Permite a exclusão lógica de um incidente.'},
            
            # Infraestrutura
            {'name': 'Criar/Editar Site', 'slug': 'manage_sites', 'module': 'Infraestrutura', 'desc': 'Permite gerenciar sites no Netbox.'},
            
            # Segurança / RBAC
            {'name': 'Gerenciar Acessos', 'slug': 'view_acessos', 'module': 'Segurança', 'desc': 'Acesso à tela de matriz de permissões.'},
            {'name': 'Alterar Permissões', 'slug': 'manage_permissions', 'module': 'Segurança', 'desc': 'Capacidade de trocar flags na matriz.'},
            
            # SEA Protocol
            {'name': 'Disparar Protocolo SEA', 'slug': 'trigger_sea_protocol', 'module': 'SEA Protocol', 'desc': 'Permissão para gerar o número de protocolo oficial.'},
            {'name': 'Ver Logs de Sequência', 'slug': 'view_sequence_logs', 'module': 'SEA Protocol', 'desc': 'Visualizar erros de sequência do PostgreSQL.'},
        ]

        for p_data in permissions:
            perm, created = UIPermission.objects.update_or_create(
                slug=p_data['slug'],
                defaults={
                    'name': p_data['name'],
                    'module': p_data['module'],
                    'description': p_data['desc']
                }
            )
            if created:
                self.stdout.write(f"✅ Criada: {perm.name}")

        # Garantir existência dos grupos básicos
        groups = ['N1', 'N2', 'Gestão']
        for g_name in groups:
            Group.objects.get_or_create(name=g_name)

        self.stdout.write(self.style.SUCCESS("✨ RBAC semeado com sucesso!"))
