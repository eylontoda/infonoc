from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

# [CRÍTICO] Define o namespace para ser usado como 'users:nome_da_rota'
app_name = 'users'

urlpatterns = [
    # Login e Logout
    path('login/', views.UserLoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    
    # Dashboard Principal
    path('', views.HomeView.as_view(), name='home'),
    
    # [CRÍTICO] Endpoint do ASGI para os Balões (Stats)
    # Rota: /users/api/stats/  (ou dependente do mount point do projeto principal)
    path('api/stats/', views.api_dashboard_stats, name='api_dashboard_stats'),

    # Endpoint do ASGI para a Tabela Dinâmica (Lista)
    path('api/incidents/', views.api_incidents_list, name='api_incidents_list'),
    
    # Página de Informativos
    path('informativos/', views.InformativosView.as_view(), name='informativos'),
    

    # ==============================================================================
    # [NOVO] ROTAS HTMX / OFFCANVAS
    # Consumidas pelo frontend para carregar formulários e painéis laterais sem refresh
    # ==============================================================================
    path('incidents/detalhe-ajax/<str:protocolo>/', views.detalhe_incidente_ajax, name='detalhe_incidente_ajax'),
    path('incidents/atualizar-ajax/<str:protocolo>/', views.atualizar_incidente_ajax, name='atualizar_incidente_ajax'),
    path('incidents/editar-ajax/<str:protocolo>/', views.editar_incidente_ajax, name='editar_incidente_ajax'),
    path('incidents/resgatar-ajax/<str:protocolo>/', views.resgatar_incidente_ajax, name='resgatar_incidente_ajax'),
    path('incidents/liberar-ajax/<str:protocolo>/', views.liberar_incidente_ajax, name='liberar_incidente_ajax'),
    path('incidents/excluir-ajax/<str:protocolo>/', views.excluir_incidente_ajax, name='excluir_incidente_ajax'),
    path('novo-ajax/', views.novo_incidente_ajax, name='novo_incidente_ajax'),


    # --- [ROTAS FANTASMA DO SEU CRUD] ---
    # Temporárias para garantir que os botões de ação tradicionais não gerem erros 500.
    # Quando migrar o CRUD totalmente para HTMX, estas rotas podem ser removidas ou reajustadas.
    path('novo/', views.HomeView.as_view(), name='novo_informativo'),
    path('informativo/<int:pk>/', views.HomeView.as_view(), name='detalhe_informativo'),
    path('informativo/<int:pk>/editar/', views.HomeView.as_view(), name='editar_informativo'),
]