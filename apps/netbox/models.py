from django.db import models
from apps.core.models import BaseModel
from simple_history.models import HistoricalRecords

class Region(BaseModel):
    netbox_id = models.IntegerField(unique=True, null=True, blank=True, db_index=True)
    name = models.CharField(max_length=50, unique=True)
    class Meta:
        verbose_name = "Região"
        verbose_name_plural = "Regiões"
    def __str__(self): return self.name

class Vendor(BaseModel):
    netbox_id = models.IntegerField(unique=True, null=True, blank=True, db_index=True)
    name = models.CharField(max_length=50, unique=True)
    class Meta:
        verbose_name = "Fabricante"
        verbose_name_plural = "Fabricantes"
    def __str__(self): return self.name

class Tenant(BaseModel):
    netbox_id = models.IntegerField(unique=True, null=True, blank=True, db_index=True)
    name = models.CharField(max_length=100, unique=True, null=True, blank=True)
    class Meta:
        verbose_name = "Fornecedor"
        verbose_name_plural = "Fornecedores"
    def __str__(self): return self.name

class SiteType(BaseModel):
    name = models.CharField(max_length=50, unique=True)
    class Meta:
        verbose_name = "Tipo de Site"
        verbose_name_plural = "Tipos de Site"
    def __str__(self): return self.name

class NetboxStatus(BaseModel):
    name = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(max_length=50, unique=True)
    class Meta:
        verbose_name = "Status Netbox"
        verbose_name_plural = "Status Netbox"
    def __str__(self): return self.name

class Site(BaseModel):
    netbox_id = models.IntegerField(unique=True, null=True, blank=True, db_index=True)
    name = models.CharField(max_length=100)
    facility = models.CharField(max_length=50, null=True, blank=True)
    region = models.ForeignKey(Region, on_delete=models.PROTECT, related_name='sites')
    coordinate = models.CharField(max_length=50, null=True, blank=True)
    physical_address = models.TextField(null=True, blank=True)
    site_type = models.ForeignKey(SiteType, on_delete=models.PROTECT)
    contract_energy = models.CharField(max_length=100, unique=True, null=True, blank=True)
    netbox_status = models.ForeignKey(NetboxStatus, on_delete=models.PROTECT, null=True, blank=True)
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, null=True, blank=True)
    history = HistoricalRecords()
    class Meta:
        verbose_name = "Site"
        verbose_name_plural = "Sites"
    def __str__(self): return self.name

class DeviceType(BaseModel):
    netbox_id = models.IntegerField(unique=True, null=True, blank=True, db_index=True)
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, related_name='device_types')
    name = models.CharField(max_length=50)
    class Meta:
        verbose_name = "Modelo de Equipamento"
        verbose_name_plural = "Modelos de Equipamentos"
    def __str__(self): return f"{self.vendor.name} {self.name}"

class Role(BaseModel):
    netbox_id = models.IntegerField(unique=True, null=True, blank=True, db_index=True)
    name = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(max_length=50, unique=True)
    class Meta:
        verbose_name = "Função de Equipamento"
        verbose_name_plural = "Funções de Equipamentos"
    def __str__(self): return self.name

class Device(BaseModel):
    netbox_id = models.IntegerField(unique=True, null=True, blank=True, db_index=True)
    name = models.CharField(max_length=100)
    device_type = models.ForeignKey(DeviceType, on_delete=models.PROTECT)
    role = models.ForeignKey(Role, on_delete=models.PROTECT)
    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name='devices')
    primary_ip = models.GenericIPAddressField(null=True, blank=True)
    netbox_status = models.ForeignKey(NetboxStatus, on_delete=models.PROTECT, null=True, blank=True)
    is_active = models.BooleanField(default=False)
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, null=True, blank=True)
    history = HistoricalRecords()
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['name', 'site'], 
                condition=models.Q(is_active=True),
                name='unique_active_device_per_site'
            )
        ]
    def save(self, *args, **kwargs):
        if self.netbox_status_id:
            self.is_active = (self.netbox_status.slug == 'active')
        super().save(*args, **kwargs)
    def __str__(self): 
        return f"{self.name} ({self.site.name})"

class Provider(BaseModel):
    netbox_id = models.IntegerField(unique=True, null=True, blank=True, db_index=True)
    name = models.CharField(max_length=50)
    slug = models.SlugField(max_length=50, unique=True) 
    class Meta:
        verbose_name = "Provedor"
        verbose_name_plural = "Provedores"
    def __str__(self): return self.name

class CircuitType(BaseModel):
    netbox_id = models.IntegerField(unique=True, null=True, blank=True, db_index=True)
    name = models.CharField(max_length=50)
    slug = models.SlugField(max_length=50, unique=True) 
    description = models.CharField(max_length=100)
    class Meta:
        verbose_name = "Tipo de Circuito"
        verbose_name_plural = "Tipos de Circuito"
    def __str__(self): return self.name

class Circuit(BaseModel):
    netbox_id = models.IntegerField(unique=True, null=True, blank=True, db_index=True)
    name = models.CharField(max_length=100, default='')
    type = models.ForeignKey(CircuitType, on_delete=models.PROTECT, null=True, blank=True)
    provider = models.ForeignKey(Provider, on_delete=models.PROTECT, related_name='circuits')
    netbox_status = models.ForeignKey(NetboxStatus, on_delete=models.PROTECT, null=True, blank=True)
    site_a = models.ForeignKey(Site, on_delete=models.PROTECT, related_name='circuits_as_a',null=True, blank=True)
    site_z = models.ForeignKey(Site, on_delete=models.PROTECT, related_name='circuits_as_z',null=True, blank=True)
    external_identifier = models.CharField(max_length=50, null=True, blank=True)
    class Meta:
        verbose_name = "Circuito"
        verbose_name_plural = "Circuitos"
    def __str__(self): return f"{self.id} - {self.name}"
