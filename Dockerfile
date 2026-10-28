FROM python:3.11-slim

WORKDIR /app

# Instala dependências de compilação essenciais e utilitários
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copia e instala requirements primeiro para aproveitar cache de camadas do Docker
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia código da aplicação e base de conhecimento
COPY . .

# Expõe as portas da API (8000) e do Streamlit (8501)
EXPOSE 8000 8501

# Comando default: inicia a API FastAPI
CMD ["uvicorn", "app.api.server:app", "--host", "0.0.0.0", "--port", "8000"]
