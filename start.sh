#!/bin/bash
set -o errexit
set -o pipefail
set -o nounset

echo "==> [START] Aguardando inicialização do ambiente..."

# [NOVO] Defesa proativa contra erros de permissão em produção
echo "==> [START] Garantindo existência e permissões em diretórios de escrita..."
mkdir -p staticfiles media
chmod -R 755 staticfiles media

echo "==> [START] Executando migrações do banco de dados..."
python manage.py migrate --noinput

echo "==> [START] Coletando arquivos estáticos para o WhiteNoise..."
python manage.py collectstatic --noinput

echo "==> [START] Iniciando servidor ASGI (Gunicorn + Uvicorn)..."
# Usando Gunicorn como gerenciador de processos e Uvicorn como worker class.
# - O 'exec' substitui o processo do bash pelo Gunicorn (PID 1), vital para Graceful Shutdown.
# - --workers: Quantidade de processos paralelos (ideal: 2 x cores + 1).
# - --timeout 120: Previne que requisições presas travem o worker indefinidamente.
# - --access-logfile / --error-logfile -: Envia logs para stdout/stderr (Docker standard).

WORKERS=${WEB_CONCURRENCY:-4}

exec gunicorn config.asgi:application \
    --bind 0.0.0.0:8000 \
    --workers "$WORKERS" \
    --worker-class uvicorn.workers.UvicornWorker \
    --timeout 120 \
    --keep-alive 5 \
    --access-logfile - \
    --error-logfile -