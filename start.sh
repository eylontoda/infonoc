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

echo "==> [START] Iniciando servidor ASGI (Uvicorn)..."
# O 'exec' substitui o processo do bash pelo Uvicorn (PID 1), 
# vital para o Graceful Shutdown do Docker.
exec uvicorn config.asgi:application --host 0.0.0.0 --port 8000 --workers 4