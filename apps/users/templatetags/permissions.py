from django import template

register = template.Library()

@register.simple_tag(takes_context=True)
def can_user(context, action_slug):
    """
    Uso: {% can_user 'btn_close_incident' as has_perm %}
    {% if has_perm %} ... {% endif %}
    """
    request = context.get('request')
    if not request or not request.user.is_authenticated:
        return False
    
    if request.user.is_superuser:
        return True
    
    # Busca se algum grupo do usuário tem essa permissão de UI
    return request.user.groups.filter(ui_permissions__slug=action_slug).exists()
