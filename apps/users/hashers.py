# apps/users/hashers.py
from django.contrib.auth.hashers import BasePasswordHasher
from werkzeug.security import check_password_hash

class WerkzeugPasswordHasher(BasePasswordHasher):
    # [NOVO] Deve ser exatamente o que o Django extrai antes do primeiro $
    algorithm = "pbkdf2:sha256:600000"

    def verify(self, password, encoded):
        # A biblioteca werkzeug já sabe lidar com o prefixo, salt e hash.
        return check_password_hash(encoded, password)

    def safe_summary(self, encoded):
        return {'algorithm': self.algorithm}
        
    def must_update(self, encoded):
        # Retornar True força o Django a converter para o formato padrão dele (com $)
        # assim que o usuário logar com sucesso.
        return True