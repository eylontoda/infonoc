// Adicionar no início do arquivo, antes de qualquer outro código
const Utils = {
    getStatusBadgeClass(status) {
        const classes = {
            'ATIVO': 'bg-primary',
            'EM ANDAMENTO': 'bg-primary',
            'RESOLVIDO': 'bg-success',
            'NORMALIZADO': 'bg-secondary'
        };
        return classes[status?.toUpperCase()] || 'bg-secondary';
    },

    getImpactoBadgeClass(impacto) {
        const classes = {
            'TOTAL': 'bg-danger',
            'PARCIAL': 'bg-warning text-dark',
            'INTERMITENTE': 'bg-info text-dark',
            'SEM IMPACTO': 'bg-secondary'
        };
        return classes[impacto?.toUpperCase()] || 'bg-secondary';
    },

    getAfetacaoBadgeClass(afetacaoAtiva) {
        return afetacaoAtiva ? 'bg-danger' : 'bg-success';
    },

    formatarStatus(status) {
        if (!status) return '';
        return status === status.toUpperCase() 
            ? status.toLowerCase().replace(/\b\w/g, c => c.toUpperCase())
            : status;
    },

    formatarImpacto(impacto) {
        if (!impacto) return '';
        return impacto === impacto.toUpperCase()
            ? impacto.toLowerCase().replace(/\b\w/g, c => c.toUpperCase())
            : impacto;
    }
};

// Cache de seletores DOM frequentemente usados
const DOM = {
    filtros: {
        periodo: document.getElementById('filtro-periodo'),
        dataInicial: document.getElementById('filtro-data-inicial'),
        dataFinal: document.getElementById('filtro-data-final'),
        status: document.getElementById('filtro-status'),
        tecnico: document.getElementById('filtro-tecnico'),
        impacto: document.getElementById('filtro-impacto'),
        cidade: document.getElementById('filtro-cidade'),
        categoria: document.getElementById('filtro-categoria')
    },
    tabelas: {
        relatorios: document.querySelector('#tabela-relatorios tbody'),
        produtividade: document.getElementById('tabela-produtividade'),
        historicoTecnico: document.querySelector('#tabela-historico-tecnico tbody')
    },
    vistas: {
        tabela: document.getElementById('vista-tabela'),
        cards: document.getElementById('vista-cards')
    }
};

// Configurações globais
const CONFIG = {
    atualizacaoAutomatica: 300000, // 5 minutos
    formatoData: {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    },
    paginacao: {
        itensPorPagina: 10,
        dadosDetalhados: {
            paginaAtual: 1,
            totalPaginas: 1,
            dados: []
        },
        todosInformativos: {
            paginaAtual: 1,
            totalPaginas: 1,
            dados: []
        }
    }
};

// Objeto para gerenciar os gráficos
const Charts = {
    instances: {},

    create(id, config) {
        if (this.instances[id]) {
            this.instances[id].destroy();
        }
        const ctx = document.getElementById(id);
        if (ctx) {
            this.instances[id] = new Chart(ctx, config);
        }
    },

    updateAll(data) {
        this.createStatusChart(data.metricas_gerais);
        this.createImpactChart(data.distribuicao_impacto);
        this.createSLAChart(data.metricas_gerais);
        this.updateMetrics(data.metricas_gerais);
        this.createTrendChart(data.tendencias);
        this.createTimeDistributionChart(data.distribuicao_horarios);
        this.createRootCauseChart(data.causa_raiz);
        this.updateKPIs(data.kpis);
    },

    createStatusChart(data) {
        this.create('grafico-status', {
            type: 'pie',
            data: {
                labels: ['Resolvidos', 'Em Andamento'],
                datasets: [{
                    data: [data.percentual_resolvidos, 100 - data.percentual_resolvidos],
                    backgroundColor: ['#28a745', '#dc3545']
                }]
            },
            options: {
                responsive: true,
                plugins: {
                    legend: { position: 'bottom' }
                }
            }
        });
    },

    createImpactChart(data) {
        this.create('grafico-impacto', {
            type: 'bar',
            data: {
                labels: data.map(item => item.impacto),
                datasets: [{
                    label: 'Quantidade',
                    data: data.map(item => item.quantidade),
                    backgroundColor: '#0d6efd'
                }]
            },
            options: {
                responsive: true,
                scales: {
                    y: { beginAtZero: true }
                }
            }
        });
    },

    createSLAChart(data) {
        this.create('grafico-sla', {
            type: 'doughnut',
            data: {
                labels: ['Dentro do SLA', 'Fora do SLA'],
                datasets: [{
                    data: [data.sla_cumprido, data.sla_violado],
                    backgroundColor: ['#198754', '#dc3545']
                }]
            },
            options: {
                responsive: true,
                plugins: {
                    legend: { position: 'bottom' }
                }
            }
        });
    },

    updateMetrics(data) {
        document.getElementById('total-incidentes').textContent = data.total_incidentes;
        document.getElementById('percentual-resolvidos').textContent = `${data.percentual_resolvidos}%`;
        document.getElementById('tempo-medio').textContent = `${data.tempo_medio_resolucao}h`;
        document.getElementById('incidentes-criticos').textContent = data.incidentes_criticos;
        
        // Atualizar SLA percentual
        const totalSLA = data.sla_cumprido + data.sla_violado;
        const percentualSLA = totalSLA > 0 ? ((data.sla_cumprido / totalSLA) * 100).toFixed(1) : 0;
        document.getElementById('sla-percentual').textContent = `${percentualSLA}%`;
    },

    createTrendChart(data) {
        this.create('grafico-tendencia-incidentes', {
            type: 'line',
            data: {
                labels: data.labels,
                datasets: [{
                    label: 'Total de Incidentes',
                    data: data.valores,
                    borderColor: '#0d6efd',
                    tension: 0.1
                }]
            },
            options: {
                responsive: true,
                plugins: {
                    legend: { position: 'bottom' }
                },
                scales: {
                    y: { beginAtZero: true }
                }
            }
        });
    },

    createTimeDistributionChart(data) {
        this.create('grafico-distribuicao-horarios', {
            type: 'bar',
            data: {
                labels: data.labels,
                datasets: [{
                    label: 'Incidentes por Hora',
                    data: data.valores,
                    backgroundColor: '#0dcaf0'
                }]
            },
            options: {
                responsive: true,
                plugins: {
                    legend: { position: 'bottom' }
                }
            }
        });
    },

    createRootCauseChart(data) {
        this.create('grafico-causa-raiz', {
            type: 'doughnut',
            data: {
                labels: data.labels,
                datasets: [{
                    data: data.valores,
                    backgroundColor: [
                        '#0d6efd', '#dc3545', '#ffc107', 
                        '#198754', '#6c757d', '#0dcaf0'
                    ]
                }]
            },
            options: {
                responsive: true,
                plugins: {
                    legend: { position: 'bottom' }
                }
            }
        });
    },

    updateKPIs(data) {
        document.getElementById('media-diaria').textContent = data.media_diaria.toFixed(1);
        document.getElementById('taxa-reincidencia').textContent = data.taxa_reincidencia.toFixed(1) + '%';
        document.getElementById('eficiencia-resolucao').textContent = data.eficiencia_resolucao.toFixed(1) + '%';
        document.getElementById('satisfacao-cliente').textContent = data.satisfacao_cliente.toFixed(1);
        
        // Atualizar barras de progresso
        document.querySelector('#media-diaria').nextElementSibling.querySelector('.progress-bar').style.width = 
            (data.media_diaria / data.meta_media_diaria * 100) + '%';
        // ... atualizar outras barras de progresso
    },

    calcularProgressoSLA(info) {
        if (!info?.inicio_evento || !info?.sla_horas) return 0;
        try {
            const inicio = new Date(info.inicio_evento).getTime();
            const agora = new Date().getTime();
            if (isNaN(inicio) || isNaN(agora)) return 0;
            
            if (info.status === 'Resolvido') {
                if (info.data_resolucao) {
                    const dataResolucao = new Date(info.data_resolucao).getTime();
                    const slaMillis = info.sla_horas * 60 * 60 * 1000;
                    return Math.min(((dataResolucao - inicio) / slaMillis) * 100, 100);
                }
                return 100;
            }
            
            const slaMillis = info.sla_horas * 60 * 60 * 1000;            return Math.min(((agora - inicio) / slaMillis) * 100, 100);
        } catch (error) {
            // console.error('Erro ao calcular progresso SLA:', error);
            return 0;
        }
    },

    getTempoRestanteSLA(info) {
        if (!info?.inicio_evento || !info?.sla_horas) return 'SLA não definido';
        try {
            if (info.status === 'Resolvido') return 'Finalizado';
            
            const inicio = new Date(info.inicio_evento).getTime();
            const agora = new Date().getTime();
            const slaMillis = info.sla_horas * 60 * 60 * 1000;
            const restanteMillis = slaMillis - (agora - inicio);
            
            if (restanteMillis <= 0) return 'SLA Expirado';
            
            const horas = Math.floor(restanteMillis / (60 * 60 * 1000));
            const minutos = Math.floor((restanteMillis % (60 * 60 * 1000)) / (60 * 1000));            return `${horas}h ${minutos}m`;
        } catch (error) {
            // console.error('Erro ao calcular tempo restante SLA:', error);
            return 'Erro no cálculo';
        }
    },

    isSLAExpired(info) {
        if (!info?.inicio_evento || !info?.sla_horas) return false;
        try {
            if (info.status === 'Resolvido') return false;
            
            const inicio = new Date(info.inicio_evento).getTime();
            const agora = new Date().getTime();
            const slaMillis = info.sla_horas * 60 * 60 * 1000;            return (agora - inicio) > slaMillis;
        } catch (error) {
            // console.error('Erro ao verificar SLA expirado:', error);
            return false;
        }
    },

    getSLABadgeClass(info) {
        if (this.isSLAExpired(info)) return 'danger';
        const progresso = this.calcularProgressoSLA(info);
        if (progresso < 50) return 'normal';
        if (progresso < 75) return 'warning';
        return 'danger';
    },

    getSLAProgressClass(info) {
        const progresso = this.calcularProgressoSLA(info);
        if (progresso < 50) return 'bg-success';
        if (progresso < 75) return 'bg-warning';
        return 'bg-danger';
    },

    getSLATimeClass(info) {
        const progresso = this.calcularProgressoSLA(info);
        if (progresso < 50) return 'normal';
        if (progresso < 75) return 'warning';
        return 'danger';
    }
};

// Função principal para atualizar relatórios
async function atualizarRelatorios() {
    try {
        const filtros = {
            periodo: document.getElementById('filtro-periodo')?.value || '30',
            status: document.getElementById('filtro-status')?.value || 'todos',
            tecnico: document.getElementById('filtro-tecnico')?.value || 'todos',
            impacto: document.getElementById('filtro-impacto')?.value || 'todos',
            cidade: document.getElementById('filtro-cidade')?.value || 'todos',
            categoria: document.getElementById('filtro-categoria')?.value || 'todos'
        };
        
        // Se for período personalizado, incluir as datas específicas
        if (filtros.periodo === 'personalizado') {
            const dataInicial = document.getElementById('filtro-data-inicial')?.value;
            const dataFinal = document.getElementById('filtro-data-final')?.value;
            if (dataInicial) filtros.data_inicial = dataInicial;
            if (dataFinal) filtros.data_final = dataFinal;
        }

        const queryString = Object.entries(filtros)
            .map(([key, value]) => `${key}=${encodeURIComponent(value)}`)
            .join('&');

        const response = await fetch(`/api/relatorios/analise_detalhada?${queryString}`);
        
        if (!response.ok) {
            throw new Error(`Erro HTTP: ${response.status}`);
        }

        const data = await response.json();

        // Atualizar todos os componentes
        if (Charts.updateAll) {
            Charts.updateAll(data);
        }

        // Armazenar dados para paginação
        if (data.informativos && Array.isArray(data.informativos)) {
            CONFIG.paginacao.dadosDetalhados.dados = data.informativos;
            CONFIG.paginacao.dadosDetalhados.totalPaginas = Math.ceil(data.informativos.length / CONFIG.paginacao.itensPorPagina);
            CONFIG.paginacao.dadosDetalhados.paginaAtual = 1;
        }

        // Atualizar tabelas se necessário
        const activeTab = document.querySelector('.tab-pane.active');
        if (activeTab?.id === 'todos-informativos') {
            recarregarTodosInformativos();
        } else if (activeTab?.id === 'dados') {
            atualizarTabela();
        }

        // Mostrar notificação de sucesso
        const toast = Swal.mixin({
            toast: true,
            position: 'top-end',
            showConfirmButton: false,
            timer: 3000
        });

        toast.fire({
            icon: 'success',
            title: 'Relatórios atualizados com sucesso'
        });    } catch (error) {
        // console.error('Erro ao atualizar relatórios:', error);
        Swal.fire({
            icon: 'error',
            title: 'Erro',
            text: 'Não foi possível atualizar os relatórios',
            footer: error.message
        });
    }
}

async function recarregarTodosInformativos() {
    try {
        const container = document.getElementById('todos-informativos');
        if (!container) return;
        
        // Mostrar indicador de carregamento
        container.innerHTML = `
            <div class="d-flex justify-content-center my-5">
                <div class="spinner-border text-primary" role="status">
                    <span class="visually-hidden">Carregando...</span>
                </div>
            </div>
        `;

        const filtros = {
            periodo: document.getElementById('filtro-periodo')?.value || '30',
            status: document.getElementById('filtro-status')?.value || 'todos',
            tecnico: document.getElementById('filtro-tecnico')?.value || 'todos',
            impacto: document.getElementById('filtro-impacto')?.value || 'todos',
            cidade: document.getElementById('filtro-cidade')?.value || 'todos',
            categoria: document.getElementById('filtro-categoria')?.value || 'todos'
        };

        const queryString = Object.entries(filtros)
            .map(([key, value]) => `${key}=${encodeURIComponent(value)}`)
            .join('&');

        const response = await fetch(`/informativos_todos?${queryString}`);
        const data = await response.json();
        
        if (!data.success) throw new Error(data.error || 'Erro ao carregar informativos');
        
        // Armazenar dados para paginação
        if (data.data && Array.isArray(data.data)) {
            CONFIG.paginacao.todosInformativos.dados = data.data;
            CONFIG.paginacao.todosInformativos.totalPaginas = Math.ceil(data.data.length / CONFIG.paginacao.itensPorPagina);
            CONFIG.paginacao.todosInformativos.paginaAtual = 1;
        }
        
        exibirTodosInformativos();    } catch (error) {
        // console.error('Erro:', error);
        document.getElementById('todos-informativos').innerHTML = `
            <div class="alert alert-danger">
                <i class="bi bi-exclamation-triangle"></i> Erro ao carregar informativos: ${error.message}
            </div>
        `;
    }
}

function exibirTodosInformativos() {
    const container = document.getElementById('todos-informativos');
    if (!container) return;

    const informativos = CONFIG.paginacao.todosInformativos.dados;

    if (!informativos || informativos.length === 0) {
        container.innerHTML = `
            <div class="alert alert-info">
                <i class="bi bi-info-circle"></i> Nenhum informativo encontrado.
            </div>`;
        return;
    }

    // Calcular registros da página atual
    const inicio = (CONFIG.paginacao.todosInformativos.paginaAtual - 1) * CONFIG.paginacao.itensPorPagina;
    const fim = Math.min(inicio + CONFIG.paginacao.itensPorPagina, informativos.length);
    const informativosPagina = informativos.slice(inicio, fim);

    const tableHTML = `
        <div class="table-scrollable">
            <table class="table table-hover">
                <thead class="table-light">
                    <tr>
                        <th>Protocolo</th>
                        <th>Data</th>
                        <th>Incidente</th>
                        <th>Relato</th>
                        <th>Status</th>
                        <th>Impacto</th>
                        <th>Afetação</th>
                        <th>Ações</th>
                    </tr>
                </thead>
                <tbody>
                    ${informativosPagina.map(info => {
                        // Tentar diferentes campos de data disponíveis
                        let data = 'N/A';
                        
                        // Verificar diferentes campos de data em ordem de prioridade
                        const possiveisCamposData = ['data_criacao', 'inicio_evento', 'data'];
                        
                        for (const campo of possiveisCamposData) {
                            if (info[campo]) {
                                try {
                                    const dateObj = new Date(info[campo]);
                                    if (!isNaN(dateObj.getTime())) {
                                        // Formatar apenas a data (sem a hora)
                                        data = dateObj.toLocaleDateString('pt-BR');
                                        break; // Sair do loop se encontrar uma data válida
                                    }                                } catch (e) {
                                    // console.error(`Erro ao processar o campo ${campo}:`, e);
                                }
                            }
                        }
                        
                        return `
                        <tr data-inicio-evento="${info.inicio_evento || ''}" data-sla-horas="${info.sla_horas || ''}">
                            <td>${info.protocolo || ''}</td>
                            <td>${data}</td>
                            <td>${info.incidente || 'Não definido'}</td>
                            <td class="text-break">${info.descricao || info.relato_inicial || ''}</td>
                            <td><span class="badge ${Utils.getStatusBadgeClass(Utils.formatarStatus(info.status))}">${Utils.formatarStatus(info.status) || ''}</span></td>
                            <td>
                                <span class="badge ${Utils.getImpactoBadgeClass(info.impacto || info.impacto_cliente)}">
                                    ${Utils.formatarImpacto(info.impacto || info.impacto_cliente) || 'Não definido'}
                                </span>
                            </td>
                            <td>
                                <span class="badge ${Utils.getAfetacaoBadgeClass(info.afetacao_ativa)}">
                                    ${info.afetacao_ativa ? 'Com Afetação' : 'Sem Afetação'}
                                </span>
                            </td>
                            <td>
                                <button class="btn btn-sm btn-outline-primary" onclick="verDetalhesInformativo('${info.protocolo}')">
                                    <i class="bi bi-eye"></i>
                                </button>
                            </td>
                        </tr>
                    `}).join('')}
                </tbody>
            </table>
        </div>
        <div class="d-flex justify-content-between align-items-center mt-3">
            <div>
                Exibindo ${inicio + 1} a ${fim} de ${informativos.length} registros
            </div>
            <div>
                <div class="input-group input-group-sm">
                    <label class="input-group-text">Itens por página</label>
                    <select class="form-select form-select-sm" id="itens-por-pagina-todos" onchange="alterarItensPorPagina('todosInformativos', this.value)">
                        <option value="10" ${CONFIG.paginacao.itensPorPagina === 10 ? 'selected' : ''}>10</option>
                        <option value="25" ${CONFIG.paginacao.itensPorPagina === 25 ? 'selected' : ''}>25</option>
                        <option value="50" ${CONFIG.paginacao.itensPorPagina === 50 ? 'selected' : ''}>50</option>
                        <option value="100" ${CONFIG.paginacao.itensPorPagina === 100 ? 'selected' : ''}>100</option>
                    </select>
                </div>
            </div>
            <nav aria-label="Navegação de páginas">
                <ul class="pagination pagination-sm mb-0">
                    <li class="page-item ${CONFIG.paginacao.todosInformativos.paginaAtual === 1 ? 'disabled' : ''}">
                        <a class="page-link" href="#" onclick="mudarPagina('todosInformativos', 1); return false;">
                            <i class="bi bi-chevron-double-left"></i>
                        </a>
                    </li>
                    <li class="page-item ${CONFIG.paginacao.todosInformativos.paginaAtual === 1 ? 'disabled' : ''}">
                        <a class="page-link" href="#" onclick="mudarPagina('todosInformativos', ${CONFIG.paginacao.todosInformativos.paginaAtual - 1}); return false;">
                            <i class="bi bi-chevron-left"></i>
                        </a>
                    </li>
                    ${gerarBotoesPaginas('todosInformativos')}
                    <li class="page-item ${CONFIG.paginacao.todosInformativos.paginaAtual === CONFIG.paginacao.todosInformativos.totalPaginas ? 'disabled' : ''}">
                        <a class="page-link" href="#" onclick="mudarPagina('todosInformativos', ${CONFIG.paginacao.todosInformativos.paginaAtual + 1}); return false;">
                            <i class="bi bi-chevron-right"></i>
                        </a>
                    </li>
                    <li class="page-item ${CONFIG.paginacao.todosInformativos.paginaAtual === CONFIG.paginacao.todosInformativos.totalPaginas ? 'disabled' : ''}">
                        <a class="page-link" href="#" onclick="mudarPagina('todosInformativos', ${CONFIG.paginacao.todosInformativos.totalPaginas}); return false;">
                            <i class="bi bi-chevron-double-right"></i>
                        </a>
                    </li>
                </ul>
            </nav>
        </div>
    `;

    container.innerHTML = tableHTML;
}

// Adicionar esta nova função auxiliar para formatar apenas a data (sem horário)
const formatarApenasData = data => {
    if (!data) return 'N/A';
    try {
        const dateObj = new Date(data);
        if (isNaN(dateObj.getTime())) return 'N/A';        return dateObj.toLocaleDateString('pt-BR'); // Formato DD/MM/AAAA
    } catch (error) {
        // console.error("Erro ao formatar data:", error, "Data original:", data);
        return 'N/A';
    }
};

function atualizarTabela() {
    const tbody = document.querySelector('#tabela-relatorios tbody');
    const paginacaoContainer = document.getElementById('paginacao-dados-detalhados');
    
    if (!tbody) return;

    const informativos = CONFIG.paginacao.dadosDetalhados.dados;
    
    // Se não houver dados e nenhum indicador de carregamento,
    // mostrar mensagem de carregamento e buscar os dados
    if (!informativos || informativos.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="7" class="text-center">
                    <div class="d-flex justify-content-center my-3">
                        <div class="spinner-border spinner-border-sm text-primary" role="status">
                            <span class="visually-hidden">Carregando...</span>
                        </div>
                        <span class="ms-2">Carregando dados...</span>
                    </div>
                </td>
            </tr>
        `;
        if (paginacaoContainer) paginacaoContainer.innerHTML = '';
        
        // Tentar carregar os dados novamente
        setTimeout(() => {
            const activeTabId = document.querySelector('.tab-pane.active')?.id;
            if (activeTabId === 'dados') {
                atualizarRelatorios();
            }
        }, 300);
        
        return;
    }

    // Calcular registros da página atual
    const inicio = (CONFIG.paginacao.dadosDetalhados.paginaAtual - 1) * CONFIG.paginacao.itensPorPagina;
    const fim = Math.min(inicio + CONFIG.paginacao.itensPorPagina, informativos.length);
    const informativosPagina = informativos.slice(inicio, fim);

    // Preencher tabela com os dados da página atual
    tbody.innerHTML = '';
    informativosPagina.forEach(info => {
        const row = document.createElement('tr');
        row.innerHTML = `
            <td>${info.protocolo}</td>
            <td>${formatarApenasData(info.data_criacao)}</td>
            <td>${info.tecnico}</td>
            <td><span class="badge ${getStatusBadgeClass(info.status)}">${info.status}</span></td>
            <td><span class="badge ${getImpactoBadgeClass(info.impacto)}">${info.impacto}</span></td>
            <td>${info.qtd_clientes}</td>
            <td>
                <div class="small">
                    <div>Total: ${formatarTempo(info.tempo_total)}</div>
                    <div class="text-danger">Afetação: ${formatarTempo(info.tempo_afetacao)}</div>
                </div>
            </td>
        `;
        tbody.appendChild(row);
    });

    // Atualizar controles de paginação
    paginacaoContainer.innerHTML = `
        <div class="d-flex justify-content-between align-items-center mt-3">
            <div>
                Exibindo ${inicio + 1} a ${fim} de ${informativos.length} registros
            </div>
            <div>
                <div class="input-group input-group-sm">
                    <label class="input-group-text">Itens por página</label>
                    <select class="form-select form-select-sm" id="itens-por-pagina-dados" onchange="alterarItensPorPagina('dadosDetalhados', this.value)">
                        <option value="10" ${CONFIG.paginacao.itensPorPagina === 10 ? 'selected' : ''}>10</option>
                        <option value="25" ${CONFIG.paginacao.itensPorPagina === 25 ? 'selected' : ''}>25</option>
                        <option value="50" ${CONFIG.paginacao.itensPorPagina === 50 ? 'selected' : ''}>50</option>
                        <option value="100" ${CONFIG.paginacao.itensPorPagina === 100 ? 'selected' : ''}>100</option>
                    </select>
                </div>
            </div>
            <nav aria-label="Navegação de páginas">
                <ul class="pagination pagination-sm mb-0">
                    <li class="page-item ${CONFIG.paginacao.dadosDetalhados.paginaAtual === 1 ? 'disabled' : ''}">
                        <a class="page-link" href="#" onclick="mudarPagina('dadosDetalhados', 1); return false;">
                            <i class="bi bi-chevron-double-left"></i>
                        </a>
                    </li>
                    <li class="page-item ${CONFIG.paginacao.dadosDetalhados.paginaAtual === 1 ? 'disabled' : ''}">
                        <a class="page-link" href="#" onclick="mudarPagina('dadosDetalhados', ${CONFIG.paginacao.dadosDetalhados.paginaAtual - 1}); return false;">
                            <i class="bi bi-chevron-left"></i>
                        </a>
                    </li>
                    ${gerarBotoesPaginas('dadosDetalhados')}
                    <li class="page-item ${CONFIG.paginacao.dadosDetalhados.paginaAtual === CONFIG.paginacao.dadosDetalhados.totalPaginas ? 'disabled' : ''}">
                        <a class="page-link" href="#" onclick="mudarPagina('dadosDetalhados', ${CONFIG.paginacao.dadosDetalhados.paginaAtual + 1}); return false;">
                            <i class="bi bi-chevron-right"></i>
                        </a>
                    </li>
                    <li class="page-item ${CONFIG.paginacao.dadosDetalhados.paginaAtual === CONFIG.paginacao.dadosDetalhados.totalPaginas ? 'disabled' : ''}">
                        <a class="page-link" href="#" onclick="mudarPagina('dadosDetalhados', ${CONFIG.paginacao.dadosDetalhados.totalPaginas}); return false;">
                            <i class="bi bi-chevron-double-right"></i>
                        </a>
                    </li>
                </ul>
            </nav>
        </div>
    `;
}

// Funções auxiliares para paginação
function mudarPagina(tabela, pagina) {
    if (pagina < 1 || pagina > CONFIG.paginacao[tabela].totalPaginas) return;
    
    CONFIG.paginacao[tabela].paginaAtual = pagina;
    
    if (tabela === 'todosInformativos') {
        exibirTodosInformativos();
    } else if (tabela === 'dadosDetalhados') {
        atualizarTabela();
    }
}

function alterarItensPorPagina(tabela, quantidade) {
    CONFIG.paginacao.itensPorPagina = parseInt(quantidade);
    CONFIG.paginacao[tabela].paginaAtual = 1;
    CONFIG.paginacao[tabela].totalPaginas = Math.ceil(CONFIG.paginacao[tabela].dados.length / CONFIG.paginacao.itensPorPagina);
    
    if (tabela === 'todosInformativos') {
        exibirTodosInformativos();
    } else if (tabela === 'dadosDetalhados') {
        atualizarTabela();
    }
}

function gerarBotoesPaginas(tabela) {
    const paginaAtual = CONFIG.paginacao[tabela].paginaAtual;
    const totalPaginas = CONFIG.paginacao[tabela].totalPaginas;
    
    let html = '';
    const maxBotoes = 5; // Mostrar no máximo 5 botões de páginas
    
    let inicio = Math.max(1, paginaAtual - Math.floor(maxBotoes / 2));
    let fim = Math.min(totalPaginas, inicio + maxBotoes - 1);
    
    // Ajustar início se estiver próximo do final
    if (fim - inicio + 1 < maxBotoes) {
        inicio = Math.max(1, fim - maxBotoes + 1);
    }
    
    for (let i = inicio; i <= fim; i++) {
        html += `
            <li class="page-item ${i === paginaAtual ? 'active' : ''}">
                <a class="page-link" href="#" onclick="mudarPagina('${tabela}', ${i}); return false;">${i}</a>
            </li>
        `;
    }
    
    return html;
}

// Adicionar a definição da função carregarTecnicos
async function carregarTecnicos() {
    try {
        const response = await fetch('/listar_usuarios');
        if (!response.ok) throw new Error('Erro ao carregar técnicos');
        
        const usuarios = await response.json();
        const selectTecnico = document.getElementById('filtro-tecnico');
        if (!selectTecnico) return;
        
        // Manter a opção "Todos"
        const optionTodos = selectTecnico.querySelector('option[value="todos"]');
        selectTecnico.innerHTML = '';
        if (optionTodos) {
            selectTecnico.appendChild(optionTodos);
        } else {
            const option = document.createElement('option');
            option.value = 'todos';
            option.textContent = 'Todos';
            selectTecnico.appendChild(option);
        }
        
        // Adicionar apenas usuários do tipo técnico
        if (usuarios && Array.isArray(usuarios)) {
            usuarios
                .filter(u => u.tipo === 'tecnico')
                .forEach(tecnico => {
                    const option = document.createElement('option');
                    option.value = tecnico.username;
                    option.textContent = tecnico.username;
                    selectTecnico.appendChild(option);
                });
        }    } catch (error) {
        // console.error('Erro ao carregar técnicos:', error);
        // Exibir mensagem de erro na interface se necessário
    }
}

// Função para inicializar os selects com suas opções
function inicializarSelects() {
    // Inicializar select de status
    const selectStatus = document.getElementById('filtro-status');
    if (selectStatus && selectStatus.children.length <= 1) {
        selectStatus.innerHTML = `
            <option value="todos">Todos</option>
            <option value="Em Andamento">Em Andamento</option>
            <option value="Resolvido">Resolvido</option>
            <option value="Normalizado">Normalizado</option>
        `;
    }
    
    // Inicializar select de impacto
    const selectImpacto = document.getElementById('filtro-impacto');
    if (selectImpacto && selectImpacto.children.length <= 1) {
        selectImpacto.innerHTML = `
            <option value="todos">Todos</option>
            <option value="Total">Total</option>
            <option value="Parcial">Parcial</option>
            <option value="Intermitente">Intermitente</option>
            <option value="Sem Impacto">Sem Impacto</option>
        `;
    }
    
    // Inicializar select de categoria
    const selectCategoria = document.getElementById('filtro-categoria');
    if (selectCategoria && selectCategoria.children.length <= 1) {
        selectCategoria.innerHTML = `
            <option value="todos">Todos</option>
            <option value="Banda Larga">Banda Larga</option>
            <option value="Dedicado">Dedicado</option>
            <option value="Banda Larga & Dedicado">Banda Larga & Dedicado</option>
        `;
    }
    
    // Inicializar select de cidade (será preenchido dinamicamente)
    const selectCidade = document.getElementById('filtro-cidade');
    if (selectCidade && selectCidade.children.length <= 1) {
        selectCidade.innerHTML = '<option value="todos">Todas</option>';
    }
    
    // Inicializar select de técnico (será preenchido dinamicamente)
    const selectTecnico = document.getElementById('filtro-tecnico');
    if (selectTecnico && selectTecnico.children.length <= 1) {
        selectTecnico.innerHTML = '<option value="todos">Todos</option>';
    }
}

// Também assegurar que as funções utilizadas na paginação estão definidas (caso haja outros erros)
function formatarTempo(horas) {
    if (!horas) return 'N/A';
    const h = Math.floor(horas);
    const m = Math.round((horas - h) * 60);
    return `${h}h ${m}m`;
}

const formatarData = data => {
    if (!data) return 'N/A';
    try {        return new Date(data).toLocaleString('pt-BR', CONFIG.formatoData);
    } catch (error) {
        // console.error("Erro ao formatar data:", error, "Data original:", data);
        return 'N/A';
    }
};

const getStatusBadgeClass = status => {
    return Utils.getStatusBadgeClass(status);
};

const getImpactoBadgeClass = impacto => {
    return Utils.getImpactoBadgeClass(impacto);
};

// Função para ver detalhes de um informativo
async function verDetalhesInformativo(protocolo) {
    try {
        // Exibir indicador de carregamento
        Swal.fire({
            title: 'Carregando...',
            text: 'Buscando detalhes do informativo',
            allowOutsideClick: false,
            showConfirmButton: false,
            willOpen: () => {
                Swal.showLoading();
            }
        });        const protocoloLimpo = protocolo.trim();
        // console.log(`Buscando detalhes do informativo: ${protocoloLimpo}`);
          const response = await fetch(`/buscar_informativo/${encodeURIComponent(protocoloLimpo)}`);
        
        // Fechar o indicador de carregamento
        Swal.close();
        
        if (!response.ok) {
            throw new Error(`Erro HTTP: ${response.status}`);
        }
        
        const data = await response.json();
        
        if (!data.success) {
            throw new Error(data.error || 'Erro ao carregar detalhes');
        }
        
        const info = data.data;
        // console.log("Detalhes do informativo recebidos:", info);
        
        // Criar modal via Bootstrap
        const modalHTML = `
            <div class="modal fade" id="modalDetalhesInformativo-${protocoloLimpo}" tabindex="-1" aria-labelledby="modalLabel-${protocoloLimpo}" aria-hidden="true">
                <div class="modal-dialog modal-lg">
                    <div class="modal-content theme-aware">
                        <div class="modal-header bg-primary text-white">
                            <h5 class="modal-title" id="modalLabel-${protocoloLimpo}">Informativo ${info.protocolo}</h5>
                            <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal" aria-label="Close"></button>
                        </div>
                        <div class="modal-body">
                            <div class="row">
                                <div class="col-md-6">
                                    <p><strong>Protocolo:</strong> ${info.protocolo || 'N/A'}</p>
                                    <p><strong>Incidente:</strong> ${info.incidente || 'Não definido'}</p>
                                    <p><strong>Ofensor:</strong> ${info.ofensor || 'Não definido'}</p>
                                    <p><strong>Equipe:</strong> ${info.equipe_acionada || 'N/A'}</p>
                                    <p><strong>Local:</strong> ${info.local_afetado || 'N/A'}</p>
                                    <p><strong>Clientes:</strong> ${info.qtd_clientes || '0'}</p>
                                </div>
                                <div class="col-md-6">
                                    <p><strong>Categoria:</strong> ${info.categoria_clientes || 'N/A'}</p>
                                    <p><strong>Status:</strong> <span class="badge ${Utils.getStatusBadgeClass(info.status)}">${Utils.formatarStatus(info.status) || 'N/A'}</span></p>
                                    <p><strong>Atendente:</strong> ${info.atendente_noc || 'N/A'}</p>
                                    <p><strong>Início:</strong> ${formatarData(info.inicio_evento) || 'N/A'}</p>
                                    ${info.previsao_normalizacao ? 
                                        `<p><strong>Previsão:</strong> ${formatarData(info.previsao_normalizacao)}</p>` 
                                        : ''}
                                </div>
                            </div>
                            <hr>
                            <h6>Relato:</h6>
                            <div class="modal-text-container">
                                ${info.descricao || info.relato_inicial || 'Sem relato disponível'}
                            </div>
                            ${info.historico?.length ? `
                                <h6>Histórico:</h6>
                                <div class="modal-text-container" style="max-height: 200px; overflow-y: auto;">
                                    ${info.historico.map(h => `
                                        <div class="mb-2">
                                            <small class="text-muted">
                                                ${h.data || ''} - ${h.usuario || ''}
                                            </small>
                                            <div>${h.descricao || ''}</div>
                                            <small class="text-muted">
                                                Status: 
                                                <span class="badge ${Utils.getStatusBadgeClass(Utils.formatarStatus(h.status_anterior))}">
                                                    ${Utils.formatarStatus(h.status_anterior) || ''}
                                                </span> → 
                                                <span class="badge ${Utils.getStatusBadgeClass(Utils.formatarStatus(h.status_novo))}">
                                                    ${Utils.formatarStatus(h.status_novo) || ''}
                                                </span>
                                            </small>
                                        </div>
                                    `).join('<hr>')}
                                </div>
                            ` : '<p>Nenhum histórico disponível</p>'}
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Fechar</button>
                        </div>
                    </div>
                </div>
            </div>
        `;
        
        // Remover modal anterior se existir
        const modalAnterior = document.getElementById(`modalDetalhesInformativo-${protocoloLimpo}`);
        if (modalAnterior) {
            modalAnterior.remove();
        }
        
        // Adicionar o modal ao DOM
        document.body.insertAdjacentHTML('beforeend', modalHTML);
        
        // Exibir o modal
        const modal = new bootstrap.Modal(document.getElementById(`modalDetalhesInformativo-${protocoloLimpo}`));
        modal.show();    } catch (error) {
        // console.error('Erro ao carregar detalhes do informativo:', error);
        Swal.fire({
            icon: 'error',
            title: 'Erro',
            text: 'Não foi possível carregar os detalhes do informativo',
            footer: error.message
        });
    }
}

// Função para atualizar período automaticamente
function atualizarPeriodo() {
    const filtro = document.getElementById('filtro-periodo');
    const dataInicial = document.getElementById('filtro-data-inicial');
    const dataFinal = document.getElementById('filtro-data-final');
    
    if (!filtro || !dataInicial || !dataFinal) return;
    
    const hoje = new Date();
    const valorPeriodo = filtro.value;
    
    // Sempre definir data final como hoje
    dataFinal.value = hoje.toISOString().split('T')[0];
    
    // Calcular data inicial baseada no período selecionado
    let dataInicio = new Date(hoje);
    
    switch(valorPeriodo) {
        case 'hoje':
            dataInicio = new Date(hoje);
            break;
        case '7':
            dataInicio.setDate(hoje.getDate() - 7);
            break;
        case '15':
            dataInicio.setDate(hoje.getDate() - 15);
            break;
        case '30':
            dataInicio.setDate(hoje.getDate() - 30);
            break;
        case '60':
            dataInicio.setDate(hoje.getDate() - 60);
            break;
        case '90':
            dataInicio.setDate(hoje.getDate() - 90);
            break;
        case 'personalizado':
            // Não alterar as datas se for personalizado
            return;
        default:
            dataInicio.setDate(hoje.getDate() - 30); // Padrão 30 dias
    }
    
    dataInicial.value = dataInicio.toISOString().split('T')[0];
    
    // Atualizar relatórios automaticamente
    atualizarRelatorios();
}

// Gerenciador de permissões
const PermissionManager = {
    userPermissions: [],
      init() {
        // console.log("Inicializando PermissionManager");
        // Tentar carregar as permissões do usuário a partir do script incorporado
        if (typeof userPermissions !== 'undefined') {
            this.userPermissions = userPermissions;
            // console.log("Permissões carregadas:", this.userPermissions);
        } else {
            // console.log("userPermissions não definido, tentando carregar via API");
            this.loadUserPermissions();
        }
        
        // Aplicar verificação de permissões para as abas
        this.applyTabPermissions();
        
        // Adicionar handlers para evitar acesso não autorizado
        this.setupPermissionHandlers();
    },
    
    async loadUserPermissions() {
        try {
            const response = await fetch('/api/user/permissions');
            if (response.ok) {                const data = await response.json();
                this.userPermissions = data.permissions || [];
                // console.log("Permissões carregadas via API:", this.userPermissions);
                // Aplicar permissões após carregamento
                this.applyTabPermissions();
                return true;            }
        } catch (error) {
            // console.error('Erro ao carregar permissões:', error);
        }
        return false;
    },
    
    hasPermission(permissionCode) {
        if (!permissionCode) return false;
        
        // Se tiver permissão coringa (*) ou for superadmin/admin, permitir tudo
        if (this.userPermissions.includes('*') || 
            this.userPermissions.includes('admin') || 
            this.userPermissions.includes('superadmin')) {
            return true;
        }
        
        return this.userPermissions.includes(permissionCode);
    },    applyTabPermissions() {
        // console.log("Aplicando permissões às abas");
        
        // Verificar todas as abas que precisam de permissão
        document.querySelectorAll('.nav-item[data-permission]').forEach(tab => {
            const permission = tab.getAttribute('data-permission');
            const hasPermission = this.hasPermission(permission);
            
            // console.log(`Verificando permissão para aba: ${permission} - Acesso: ${hasPermission}`);
            
            // Se o usuário não tem permissão, ocultar a aba
            if (!hasPermission) {
                tab.style.display = 'none';
            } else {
                tab.style.display = '';  // Mostrar a aba se tiver permissão
            }
        });
    },
    
    setupPermissionHandlers() {
        document.querySelectorAll('.nav-item[data-permission]').forEach(tab => {
            const permission = tab.getAttribute('data-permission');
            const button = tab.querySelector('button');
            
            if (button) {
                button.addEventListener('click', (event) => {                    if (!this.hasPermission(permission)) {
                        event.preventDefault();
                        event.stopPropagation();
                        
                        // console.log(`Acesso negado à aba: ${permission}`);
                        
                        // Mostrar modal de acesso negado
                        const deniedModal = new bootstrap.Modal(document.getElementById('permissionDeniedModal'));
                        deniedModal.show();
                        
                        return false;
                    }
                });
            }
        });
    }
};

// Funções de exportação
function exportarExcel() {
    // TODO: Implementar exportação para Excel
    Swal.fire({
        icon: 'info',
        title: 'Funcionalidade em desenvolvimento',
        text: 'A exportação para Excel será implementada em breve.'
    });
}

function exportarPDF() {
    // TODO: Implementar exportação para PDF
    Swal.fire({
        icon: 'info',
        title: 'Funcionalidade em desenvolvimento',
        text: 'A exportação para PDF será implementada em breve.'
    });
}

// Função para carregar relatório de produtividade
async function carregarRelatorioProdutividade() {
    try {
        const response = await fetch('/api/relatorios/produtividade');
        if (!response.ok) {
            throw new Error('Erro ao carregar produtividade');
        }
        const data = await response.json();
        
        // Atualizar tabela de produtividade se existir
        const tabela = document.getElementById('tabela-produtividade');
        if (tabela && data.tecnicos) {
            // Implementar preenchimento da tabela de produtividade
            console.log('Dados de produtividade:', data);
        }
    } catch (error) {
        console.warn('Relatório de produtividade não disponível:', error.message);
    }
}

// Função para alternar visualização (referenciada no HTML)
function alternarVisualizacao(tipo) {
    const vistaTabela = document.getElementById('vista-tabela');
    const vistaCards = document.getElementById('vista-cards');
    
    if (!vistaTabela || !vistaCards) return;
    
    if (tipo === 'tabela') {
        vistaTabela.style.display = 'block';
        vistaCards.style.display = 'none';
    } else if (tipo === 'cards') {
        vistaTabela.style.display = 'none';
        vistaCards.style.display = 'flex';
    }
}

// Inicialização
document.addEventListener('DOMContentLoaded', () => {
    const sessionTipo = document.body.dataset.sessionTipo; // Adicionar data-session-tipo="admin" no body do template
    
    // Inicializar selects com opções padrão
    inicializarSelects();
    
    // Carregar dados iniciais
    atualizarRelatorios();
    carregarTecnicos();
    
    if (sessionTipo === 'admin') {
        carregarRelatorioProdutividade();
    }

    // Adicionar eventos para os botões
    const btnAtualizar = document.getElementById('btn-atualizar');
    if (btnAtualizar) {
        btnAtualizar.addEventListener('click', atualizarRelatorios);
    }

    // Adicionar event listeners para todas as abas para carregar dados quando forem selecionadas
    document.querySelectorAll('[data-bs-toggle="tab"]').forEach(tabEl => {
        tabEl.addEventListener('shown.bs.tab', event => {
            const targetId = event.target.getAttribute('data-bs-target').substring(1);
            
            switch(targetId) {
                case 'todos-informativos':
                    recarregarTodosInformativos();
                    break;
                case 'dados':
                    // Se já tivermos dados, apenas atualizar a tabela, senão buscar novos
                    if (CONFIG.paginacao.dadosDetalhados.dados.length > 0) {
                        atualizarTabela();
                    } else {
                        atualizarRelatorios();
                    }
                    break;
                // Outros casos podem ser adicionados conforme necessário
            }
        });
    });
    
    // Adicionar event listeners para os filtros
    const filtros = [
        'filtro-periodo', 'filtro-status', 'filtro-tecnico', 
        'filtro-impacto', 'filtro-cidade', 'filtro-categoria'
    ];
    
    filtros.forEach(id => {
        const elemento = document.getElementById(id);
        if (elemento) {
            elemento.addEventListener('change', () => {
                // Atualizar relatórios se a aba ativa for diferente de "Todos os Informativos"
                const activeTabId = document.querySelector('.tab-pane.active')?.id;
                if (activeTabId !== 'todos-informativos') {
                    atualizarRelatorios();
                } else {
                    // Se estiver na aba "Todos os Informativos", recarregar apenas essa aba
                    recarregarTodosInformativos();
                }
            });
        }
    });

    // Verificar se a aba ativa ao carregar a página é "Todos os Informativos" ou "Dados Detalhados"
    // Isso garante que os dados apareçam se o usuário estiver inicialmente nessas abas
    const abaAtiva = document.querySelector('.tab-pane.active')?.id;
    if (abaAtiva === 'todos-informativos') {
        recarregarTodosInformativos();
    } else if (abaAtiva === 'dados') {
        atualizarTabela();
    }

    // Inicializar gerenciador de permissões
    PermissionManager.init();

    // Inicializar selects com opções padrão
    inicializarSelects();
});
