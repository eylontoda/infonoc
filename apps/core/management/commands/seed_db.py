import os
from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.management import call_command

class Command(BaseCommand):
    help = 'Orquestrador: Semeia ESTÁTICO, NETBOX e SQLite'

    def handle(self, *args, **options):
        sqlite_path = os.path.join(settings.BASE_DIR, 'backup_sqlite.db')

        try:
            self.stdout.write("🌱 [1/4] Semeando dados estáticos...")
            call_command('seed_static')

            self.stdout.write("🔌 [2/4] Sincronizando com Netbox (API)...")
            call_command('seed_netbox')

            if os.path.exists(sqlite_path):
                self.stdout.write("📦 [3/4] Migrando dados do SQLite...")
                call_command('seed_sqlite')
            else:
                self.stdout.write(self.style.WARNING(f"⚠️  Arquivo SQLite não encontrado em: {sqlite_path}. Pulando migração do SQLite."))

            self.stdout.write(self.style.SUCCESS("✨ Processo global de seed e migração concluído com sucesso!"))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"💥 Erro crítico durante o processo: {str(e)}"))
            import traceback
            self.stdout.write(traceback.format_exc())
