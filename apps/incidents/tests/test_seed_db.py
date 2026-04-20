from django.test import TestCase
from django.core.management import call_command
from django.contrib.auth import get_user_model
from unittest.mock import patch, MagicMock
import os

from apps.incidents.models import (
    Status, Incident, UpdateIncident
)
from apps.netbox.models import (
    SiteType, Vendor, Site, Provider, Role, CircuitType, Region
)

User = get_user_model()

class SeedDBCommandTest(TestCase):

    @patch('apps.core.management.commands.seed_db.Command._get_netbox_client')
    def test_seed_db_command(self, mock_get_client):
        # 1. SETUP DO MOCK NETBOX
        mock_nb = MagicMock()
        mock_get_client.return_value = mock_nb

        # 1.1 Criar Região Real (Âncora para o Site)
        Region.objects.create(netbox_id=10, name="Regiao Teste")

        # 1.2 Mock Fabricantes e Provedores
        mock_vendor = MagicMock()
        mock_vendor.id = 99
        mock_vendor.name = "Cisco Mockada"
        mock_nb.dcim.manufacturers.all.return_value = [mock_vendor]

        mock_provider = MagicMock()
        mock_provider.id = 10
        mock_provider.name = "Vivo Mockada"
        mock_provider.slug = "vivo-mockada"
        mock_nb.circuits.providers.all.return_value = [mock_provider]

        # 1.3 Mock Roles e CircuitTypes (.filter)
        mock_role = MagicMock()
        mock_role.id = 1
        mock_role.name = "Core Switch"
        mock_role.slug = "core-switch"
        mock_role.description = "" 
        mock_nb.dcim.device_roles.filter.return_value = [mock_role]

        mock_ct = MagicMock()
        mock_ct.id = 1
        mock_ct.name = "Fibra"
        mock_ct.slug = "fibra"
        mock_ct.description = ""
        mock_nb.circuits.circuit_types.filter.return_value = [mock_ct]

        # 1.4 Mock Site
        mock_site = MagicMock()
        mock_site.id = 500
        mock_site.name = "Site Teste Isolado"
        mock_site.physical_address = "" 
        mock_site.facility = ""
        mock_site.tenant = None
        mock_site.description = ""
        mock_site.custom_fields = {'abrigo': 'INDOOR'}
        mock_site.status.value = 'active'
        mock_site.status.label = 'Active'
        mock_site.region.id = 10 
        mock_site.latitude = None
        mock_site.longitude = None
        mock_nb.dcim.sites.all.return_value = [mock_site]

        # 1.5 Mocks Silenciosos
        mock_nb.dcim.regions.all.return_value = []
        mock_nb.dcim.devices.filter.return_value = []
        mock_nb.circuits.circuits.filter.return_value = []
        mock_nb.dcim.device_types.all.return_value = []

        # 2. EXECUÇÃO DO COMANDO
        # O comando vai rodar _seed_static_data, _sync_netbox e _migrate_sqlite
        call_command('seed_db')

        # 3. ASSERTS - VALIDAÇÃO NETBOX
        self.assertTrue(Role.objects.filter(name="Core Switch").exists())
        self.assertTrue(Site.objects.filter(netbox_id=500).exists())
        self.assertTrue(Provider.objects.filter(name="Vivo Mockada").exists())
        
        # 5. IMPRESSÃO DE EXEMPLOS (Chamada interna corrigida)
        self._print_table_samples()

    def _print_table_samples(self):
        """
        Imprime uma amostra de cada tabela no console para conferência manual.
        """
        models_to_check = [
            Status, SiteType, Region, Vendor, Provider, Role, CircuitType, Site, User, Incident
        ]

        print("\n" + "="*70)
        print(f"{'RELATÓRIO DE SEMENTE E MIGRAÇÃO (AMOSTRAGEM)':^70}")
        print("="*70)

        for model in models_to_check:
            obj = model.objects.first()
            model_name = model.__name__
            
            if obj:
                # Lógica para mostrar info relevante dependendo do modelo
                extra = ""
                if hasattr(obj, 'netbox_id') and obj.netbox_id:
                    extra = f" (NB ID: {obj.netbox_id})"
                elif hasattr(obj, 'mk_protocol'):
                    extra = f" (Prot: {obj.mk_protocol})"
                elif hasattr(obj, 'email'):
                    extra = f" (Email: {obj.email})"
                
                print(f" {model_name:<15} | {str(obj):<30}{extra}")
            else:
                print(f" {model_name:<15} | [VAZIO]")

        print("="*70 + "\n")