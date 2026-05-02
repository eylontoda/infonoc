from django.contrib.auth.models import AbstractUser, Group
from django.db import models
from django.core.exceptions import ValidationError
from simple_history.models import HistoricalRecords
from simple_history import register

class User(AbstractUser):
    # [NOVO] Campos migrados do seu modelo 'usuario' antigo
    is_online = models.BooleanField(default=False)
    last_access = models.DateTimeField(null=True, blank=True)
    
    # [NOVO] Auditoria de alterações no perfil do usuário
    history = HistoricalRecords()

    class Meta:
        db_table = 'auth_user'
        verbose_name = 'Usuário'
        verbose_name_plural = 'Usuários'

    def clean(self):
        super().clean()
        # Impedir remoção do último superusuário
        if self.pk and not self.is_superuser:
            was_superuser = User.objects.filter(pk=self.pk, is_superuser=True).exists()
            if was_superuser:
                superusers_count = User.objects.filter(is_superuser=True, is_active=True).count()
                if superusers_count <= 1:
                    raise ValidationError("Não é possível remover o privilégio de superusuário do único administrador ativo no sistema.")

    def save(self, *args, **kwargs):
        # Garantir que a validação seja chamada no save (Django admin faz isso, mas via shell/código não)
        if not kwargs.get('force_insert') and self.pk:
            self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.username

class UIPermission(models.Model):
    """Mapeia strings de ação para permissões de interface customizadas."""
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100, unique=True)
    module = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    groups = models.ManyToManyField(Group, related_name='ui_permissions', blank=True)
    
    history = HistoricalRecords()

    class Meta:
        verbose_name = 'Permissão de Interface'
        verbose_name_plural = 'Permissões de Interface'
        ordering = ['module', 'name']

    def __str__(self):
        return f"[{self.module}] {self.name}"

# Registrar Grupo para auditoria se ainda não estiver registrado
try:
    register(Group, app='users', history_user_id_field=models.IntegerField(null=True, blank=True))
except:
    pass