from django.contrib.auth.models import AbstractUser
from django.db import models
from simple_history.models import HistoricalRecords

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

    def __str__(self):
        return self.username