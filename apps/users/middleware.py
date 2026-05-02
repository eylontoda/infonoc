from django.http import HttpResponseForbidden
from django.urls import resolve
from apps.users.models import UIPermission

class RBACMiddleware:
    """
    Middleware para controle de acesso baseado em UIPermission.
    Verifica se a view solicitada exige uma permissão específica.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated:
            return self.get_response(request)

        if request.user.is_superuser:
            return self.get_response(request)

        # Resolve a URL atual para pegar o nome da view
        url_name = resolve(request.path_info).url_name
        
        # Lógica de mapeamento: Podemos procurar se existe uma UIPermission 
        # com o slug igual ao nome da URL ou um mapeamento específico.
        # Para este projeto, vamos procurar permissões com o slug 'view_<url_name>'
        perm_slug = f"view_{url_name}"
        
        # Se a permissão existir no sistema, validamos se o usuário a possui
        if UIPermission.objects.filter(slug=perm_slug).exists():
            if not request.user.groups.filter(ui_permissions__slug=perm_slug).exists():
                return HttpResponseForbidden("Você não tem permissão para acessar esta área.")

        return self.get_response(request)
