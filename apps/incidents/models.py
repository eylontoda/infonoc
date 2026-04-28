from django.db import models, transaction
from django.conf import settings
from django.utils import timezone
from apps.core.models import BaseModel
from simple_history.models import HistoricalRecords

# --- TABELAS AUXILIARES (Agora todas herdam BaseModel) ---

# ESTÁTICO VIA SEED
class Status(BaseModel): # [AJUSTE] Herança padronizada
    name = models.CharField(max_length=50, unique=True)
    class Meta:
        verbose_name = "Status"
        verbose_name_plural = "Status"
    def __str__(self): return self.name

# ESTÁTICO VIA SEED
class UpdateTag(BaseModel):
    name = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(max_length=50, unique=True)
    color = models.CharField(max_length=20, default="#6c757d")
    icon = models.CharField(max_length=50, null=True, blank=True)

    class Meta:
        verbose_name = "Tag de Atualização"
        verbose_name_plural = "Tags de Atualização"

    def __str__(self): return self.name

# ESTÁTICO VIA SEED
class ImpactType(BaseModel): 
    name = models.CharField(max_length=50)
    class Meta:
        verbose_name = "Tipo de Impacto"
        verbose_name_plural = "Tipos de Impactos"
    def __str__(self): return self.name

# ESTÁTICO VIA SEED
class ImpactLevel(BaseModel):
    name = models.CharField(max_length=50)
    class Meta: # [CORREÇÃO] Indentação corrigida
        verbose_name = "Nível de Impacto"
        verbose_name_plural = "Níveis de Impacto"
    def __str__(self): return self.name

# ESTÁTICO VIA SEED
class IncidentType(BaseModel):
    name = models.CharField(max_length=50)
    class Meta:
        verbose_name = "Tipo de Incidente"
        verbose_name_plural = "Tipos de Incidentes"
    def __str__(self): return self.name

class Symptom(BaseModel):
    name = models.CharField(max_length=100, unique=True)
    class Meta:
        verbose_name = "Sintoma"
        verbose_name_plural = "Sintomas"
    def __str__(self): return self.name

class DetectionSource(BaseModel):
    name = models.CharField(max_length=100, unique=True)
    class Meta:
        verbose_name = "Origem da Detecção"
        verbose_name_plural = "Origens da Detecção"
    def __str__(self): return self.name
# ESTÁTICO VIA SEED
class ClientType(BaseModel):
    name = models.CharField(max_length=50)
    class Meta: # [CORREÇÃO] Indentação corrigida
        verbose_name = "Tipo de Cliente"
        verbose_name_plural = "Tipos de Clientes"
    def __str__(self): return self.name

# ESTÁTICO VIA SEED
class RootCause(BaseModel):
    name = models.CharField(max_length=100)
    class Meta:
        verbose_name = "Causa Raiz"
        verbose_name_plural = "Causas Raiz" # [CORREÇÃO] Gramática
    def __str__(self): return self.name

# ESTÁTICO VIA SEED
class SLA(BaseModel):
    name = models.CharField(max_length=50, default="Padrão")
    class Meta:
        verbose_name = "SLA"
        verbose_name_plural = "SLAs"
    def __str__(self): return self.name

# --- TABELAS DE REFERÊNCIA (AGORA NO APP NETBOX) ---

class RegionImpactIncident(BaseModel):
    incident = models.ForeignKey('Incident', on_delete=models.CASCADE)
    region = models.ForeignKey('netbox.Region', on_delete=models.PROTECT)
    # Exemplo de campo extra que justifica o uso de 'through'
    impact_severity = models.CharField(max_length=50, null=True, blank=True)

    class Meta:
        unique_together = ('incident', 'region') # <--- Faltava o ) aqui
        verbose_name = "Impacto Regional"
        verbose_name_plural = "Impactos Regionais"

# --- TABELA PRINCIPAL ---

class Incident(BaseModel):
    mk_protocol = models.CharField(max_length=50, blank=True, db_index=True, default="")
    
    status = models.ForeignKey(Status, on_delete=models.PROTECT)
    incident_type = models.ForeignKey(IncidentType, on_delete=models.PROTECT)
    sla = models.ForeignKey(SLA, on_delete=models.PROTECT, null=True, blank=True) 

    # --- FASE 1: ABERTURA (O que sabemos agora?) ---
    detection_source = models.ForeignKey(DetectionSource, on_delete=models.PROTECT,null=True, blank=True)
    reported_symptom = models.ForeignKey(Symptom, on_delete=models.PROTECT,null=True, blank=True)
    occured_at = models.DateTimeField()
    expected_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    last_history_update_at = models.DateTimeField(null=True, blank=True)
    last_manual_update_at = models.DateTimeField(null=True, blank=True)
    stopped_at = models.DateTimeField(null=True, blank=True)
    circuit = models.ForeignKey('netbox.Circuit', on_delete=models.PROTECT, null=True, blank=True)
    site = models.ForeignKey('netbox.Site', on_delete=models.PROTECT, null=True, blank=True)
    device = models.ForeignKey('netbox.Device', on_delete=models.PROTECT, null=True, blank=True)
    root_cause = models.ForeignKey(RootCause, on_delete=models.PROTECT, null=True, blank=True)
    impact_type = models.ForeignKey(ImpactType, on_delete=models.PROTECT, null=True, blank=True)
    impact_level = models.ForeignKey(ImpactLevel, on_delete=models.PROTECT, null=True, blank=True)
    affected_regions = models.ManyToManyField(
        'netbox.Region', 
        related_name='incidents_affected', 
        blank=True, 
        verbose_name="Cidades/Regiões Afetadas"
    )
    is_impact_active = models.BooleanField(default=True)
    client_type = models.ForeignKey(ClientType, on_delete=models.PROTECT, null=True, blank=True)

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='incidents_created')
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='incidents_assigned')

    description = models.TextField()
    rfo = models.TextField(null=True, blank=True)
    note = models.TextField(null=True, blank=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "Incidente"
        verbose_name_plural = "Incidentes"

    def __str__(self):
        return f"{self.mk_protocol} - {self.status}"

# --- ATUALIZAÇÕES ---


class UpdateIncident(BaseModel):
    incident = models.ForeignKey('Incident', on_delete=models.CASCADE, related_name='updates')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, verbose_name="Autor", null=True, blank=True)

    # Conteúdo (Campos que podem mudar)
    status = models.ForeignKey('Status', on_delete=models.PROTECT)
    user_updated_at = models.DateTimeField(null=True, blank=True, verbose_name="Data/Hora da Atualização")
    is_impact_active = models.BooleanField(verbose_name="Impacto Ativo?")
    comment = models.TextField(verbose_name="Nota Técnica", null=True, blank=True)
    
    # [NOVOS] Campos para registrar o novo estado
    impact_type = models.ForeignKey('ImpactType', on_delete=models.PROTECT, null=True, blank=True)
    impact_level = models.ForeignKey('ImpactLevel', on_delete=models.PROTECT, null=True, blank=True)
    expected_at = models.DateTimeField(null=True, blank=True)
    stopped_at = models.DateTimeField(null=True, blank=True)

    tags = models.ManyToManyField(UpdateTag, related_name='updates', blank=True)

    time_elapsed = models.IntegerField(
        default=0, 
        null=True, 
        blank=True,
        help_text="Minutos decorridos desde a última atualização (ou desde a abertura)", 
        verbose_name="Tempo decorrido (Minutos)"
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = 'Atualização de Incidente'
        verbose_name_plural = 'Atualizações de Incidente'
        ordering = ['-created_at']

    def __str__(self):
        return f"Update {self.id} em {self.incident.mk_protocol}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)