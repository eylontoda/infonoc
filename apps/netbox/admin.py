from django.contrib import admin
from .models import Provider, Region, Site, Circuit, Device
from simple_history.admin import SimpleHistoryAdmin

admin.site.register([Region, Site, Circuit, Device])

@admin.register(Provider)
class ProviderAdmin(SimpleHistoryAdmin):
    list_display = ('name', 'slug')
    search_fields = ('name', 'slug')
