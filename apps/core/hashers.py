# [NOVO] Suporte para hashes vindos do Flask/Werkzeug
import hashlib
from django.contrib.auth.hashers import BasePasswordHasher, mask_hash
from django.utils.datastructures import MultiValueDict
from django.utils.translation import gettext_noop as _

class WerkzeugPasswordHasher(BasePasswordHasher):
    """
    Hasher para processar hashes do Werkzeug (Flask):
    formato: pbkdf2:sha256:600000$salt$hash_hex
    """
    algorithm = "pbkdf2:sha256" # Deve bater com o início do seu hash

    def verify(self, password, encoded):
        # O encoded vem como: pbkdf2:sha256:600000$salt$hash_hex
        algorithm, iterations, salt, hash_hex = encoded.split('$', 2)[0], *encoded.split('$')[1:]
        # No seu caso, o algoritmo tem sub-partes separadas por ':'
        parts = algorithm.split(':')
        actual_algorithm = parts[1] # sha256
        iterations = int(parts[2]) # 600000

        # Gera o hash para comparar usando a senha digitada
        hash_check = hashlib.pbkdf2_hmac(
            actual_algorithm,
            password.encode('utf-8'),
            salt.encode('utf-8'),
            iterations
        ).hex()

        return hash_check == hash_hex

    def safe_summary(self, encoded):
        algorithm, iterations, salt, hash_hex = encoded.split('$', 2)[0], *encoded.split('$')[1:]
        return {
            _("Algorithm"): algorithm,
            _("Iterations"): iterations,
            _("Salt"): mask_hash(salt),
            _("Hash"): mask_hash(hash_hex),
        }