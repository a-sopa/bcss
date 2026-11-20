# 🏆 Hackathon Picoas 2026 — Cloud Efficiency & Security with AI

Plataforma unificada de engenharia, eficiência de custos e segurança avançada para infraestruturas Cloud utilizando Inteligência Artificial, Dimensionamento Autónomo, Cache Preditivo e Criptografia Forense.

---

## 🚀 Arquitetura & Módulos da Solução

| Módulo | Área / Desafio | Descrição |
| :--- | :--- | :--- |
| **[`scraper-ai`](./scraper-ai)** | **Previsão de Tráfego & IA** | Ingestão de eventos reais (Futebol, Ticketmaster, PredictHQ, Manual, Feriados) com inferência semântica via **Google Gemini 2.5 Flash** e loop fechado de retroalimentação. |
| **[`server-preheat`](./server-preheat)** | **Dimensionamento Cloud** | Motor desacoplado de pré-aquecimento de capacidade cloud (Provisioned Concurrency AWS Lambda / Instâncias) e disparo de sondas sintéticas paralelas (JIT, DB pools e runtime). |
| **[`CacheManager`](./CacheManager)** | **Eficiência de Rede & Latência** | Serviço de cache preditivo inteligente com FastAPI e Redis, cálculo dinâmico de score multi-fator de prioridade e motor de auditoria contínua (*Self-Critic*). |
| **[`cloud_honeypot_ai`](./cloud_honeypot_ai)** | **Segurança & Eficiência Cloud + IA** | **"A Armadilha para Hackers" (Honeypot)** com análise comportamental por IA (MITRE ATT&CK), defesa perimetral automatizada (AWS NACL / SG / iptables), cofre forense criptográfico imutável (AES-256-GCM + blockchain SHA-256) e **Active Deception** (GPS Lógico de chaves API roubadas, Prompt Injection Defensivo e Beacons de Telemetria). |
| **[`bridge`](./bridge)** | **Orquestração & Benchmarking** | Ferramenta de avaliação arquitetural (`benchmark_comparison.py`) e orquestrador de relay bidirecional (`orchestrator.py`). |
| **[`JunctionX`](./JunctionX)** | **Criptografia & Postura Cloud** | QuantumTrace: Auditoria estática e dinâmica de ativos criptográficos (KMS, TLS, CBOM CycloneDX 1.6), prontidão pós-quântica (PQC) e dashboard React/Vite. |

---

## ⚡ Comandos Rápidos de Execução

### 1. Teste do Pipeline Completo (End-to-End)
Executa em menos de 1 segundo a previsão de IA, dimensionamento de servidores, sincronização de cache e verificação do honeypot:
```bash
python3 run_pipeline.py
```

### 2. Benchmark & Matriz Comparativa (Para Apresentação aos Jurados)
Gera a contagem de código em tempo real e a matriz funcional entre os módulos:
```bash
python3 bridge/benchmark_comparison.py
```

### 3. Execução Multi-Serviço com Docker Compose
O projeto inclui um `docker-compose.yml` raiz para subir toda a stack de backend e frontend em contentores:

```bash
# Iniciar Redis, CacheManager (FastAPI :8001) e Cloud Honeypot (:8888, :2222, :8080):
docker compose up -d

# Iniciar toda a stack incluindo o Frontend React (:5173):
docker compose --profile frontend up -d

# Ver o estado dos contentores:
docker compose ps

# Parar os serviços:
docker compose down
```

---

## 🛡️ Demonstração Interativa do Cloud Honeypot AI Shield

```bash
# 1. Demonstração Interativa Completa (End-to-End)
python3 -m cloud_honeypot_ai.run_honeypot demo

# 2. Iniciar Honeypots e Dashboard Web (http://localhost:8888)
python3 -m cloud_honeypot_ai.run_honeypot start

# 3. Executar a Suite de Testes (40 testes, 100% OK)
python3 -m unittest discover -s cloud_honeypot_ai/tests -v
```

---

## 🌐 Portas e Serviços em Execução

| Serviço | Porta | Descrição |
| :--- | :--- | :--- |
| **CacheManager API** | `http://localhost:8001/docs` | Swagger UI & Endpoints REST da Cache |
| **Redis Cache** | `localhost:6379` | Armazenamento de cache em memória |
| **Honeypot Dashboard** | `http://localhost:8888` | Dashboard de ameaças e replay de terminal |
| **Honeypot SSH Decoy** | `ssh -p 2222 root@localhost` | Terminal decoy com FakeShell e FakeFilesystem |
| **Honeypot Web Decoy** | `http://localhost:8080/.env` | Isco HTTP para captura de bots |
| **Frontend Web** | `http://localhost:5173` | Interface React / Tailwind |
