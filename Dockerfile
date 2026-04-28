# Alinhado com o host de desenvolvimento (Debian 12)
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install --no-install-recommends -y \
  build-essential \
  libpq-dev \
  gettext \
  libcairo2 \
  libpango-1.0-0 \
  libpangocairo-1.0-0 \
  libgdk-pixbuf2.0-0 \
  libffi-dev \
  shared-mime-info \
  && apt-get purge -y --auto-remove -o APT::AutoRemove::RecommendsImportant=false \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instala as dependências usando o cache inteligentemente
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia toda a aplicação (incluindo o seu script start.sh) para o WORKDIR
COPY . .

# Ajusta as quebras de linha e dá permissão diretamente dentro do WORKDIR
RUN sed -i 's/\r$//g' /app/start.sh && chmod +x /app/start.sh

EXPOSE 8000

# Um único ponto de entrada limpo e direto
CMD ["/app/start.sh"]