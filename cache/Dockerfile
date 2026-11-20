FROM python:3.12-slim

WORKDIR /app

# Instalar dependências de sistema mínimas se necessário
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copiar ficheiro de dependências e instalar
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar o resto do código da aplicação
COPY . .

# Criar a pasta de dados se não existir
RUN mkdir -p /app/data

# Porta onde o FastAPI corre
EXPOSE 8001

# Comando de arranque
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
