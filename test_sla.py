import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "infonoc.settings")
django.setup()
from apps.incidents.models import SLA
print([s.name for s in SLA.objects.all()])
