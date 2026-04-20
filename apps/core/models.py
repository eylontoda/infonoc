from django.db import models
from django.utils import timezone

class BaseModel(models.Model):
    # Removido o 'default', mantido apenas auto_now_add/auto_now
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        abstract = True