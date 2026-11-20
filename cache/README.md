# Cache Intelligence Module

Módulo de gestão inteligente de cache que recebe previsões do AI e faz **pre-aquecimento preditivo** da cache (Redis) com antecedência, maximizando a taxa de cache hits nas regiões e horários críticos.

## Arquitetura

```
AI Predictions (JSON file)
        │
        ▼
┌─────────────────────────┐
│   Prediction Watcher    │  ← Monitoriza ficheiro de previsões
│  (watchdog + scheduler) │
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│   Cache Planner         │  ← Gera plano de pre-aquecimento
│  (priority scoring)     │
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│   Cache Warmer          │  ← Executa pre-aquecimento no Redis
│   (async pre-fetching)  │
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│      Redis Cache        │  ← Cache em memória por região/serviço
└─────────────────────────┘
           │
┌──────────┴──────────────┐
│    FastAPI REST API     │  ← Métricas, controlo manual, status
└─────────────────────────┘
```

## Estrutura do projeto

```
cache/
├── main.py                  # Entry point FastAPI
├── requirements.txt
├── config.py                # Configurações (env vars)
├── models/
│   ├── prediction.py        # Schema das previsões do AI
│   └── cache_plan.py        # Schema do plano de cache
├── services/
│   ├── prediction_watcher.py  # Monitoriza o ficheiro JSON do AI
│   ├── cache_planner.py       # Calcula prioridades e TTLs
│   ├── cache_warmer.py        # Pre-aquece a cache no Redis
│   └── metrics.py             # Métricas de hit rate por região
├── api/
│   └── routes.py            # Endpoints REST
└── data/
    └── predictions.json     # Ficheiro partilhado com o AI (input)
```

## Como correr

```bash
# Instalar dependências
pip install -r requirements.txt

# Iniciar Redis (Docker)
docker run -d -p 6379:6379 redis:alpine

# Iniciar o serviço
python main.py
# ou
uvicorn main:app --reload --port 8001
```

## Interface com o AI

O AI escreve previsões no ficheiro `data/predictions.json`. O módulo de cache monitoriza este ficheiro e reage automaticamente.

### Formato das previsões (escrito pelo AI)

```json
{
  "generated_at": "2026-11-20T10:00:00Z",
  "predictions": [
    {
      "id": "pred-001",
      "region": "eu-west-1",
      "event_type": "football_match",
      "event_name": "Benfica vs Porto",
      "event_start": "2026-11-20T20:45:00Z",
      "lead_time_minutes": 60,
      "confidence": 0.95,
      "expected_load_multiplier": 4.5,
      "services": [
        {
          "name": "streaming_video",
          "platforms": ["DAZN", "SportTV", "Eleven"],
          "priority": 1.0,
          "cache_size_mb": 512
        },
        {
          "name": "social_media",
          "platforms": ["Twitter", "Instagram"],
          "priority": 0.7,
          "cache_size_mb": 128
        }
      ]
    }
  ]
}
```

## API Endpoints

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| GET | `/health` | Health check |
| GET | `/status` | Status geral do sistema |
| GET | `/metrics` | Métricas de hit rate por região |
| GET | `/plan` | Plano de cache atual |
| POST | `/warm/{region}` | Forçar pre-aquecimento manual |
| DELETE | `/cache/{region}` | Limpar cache de uma região |
| GET | `/predictions` | Previsões atuais carregadas |
| GET | `/critique` | Ver último relatório de autocrítica |
| POST | `/critique/run` | Forçar avaliação de autocrítica imediata |
| POST | `/simulate/hit?cache_key=...` | Simular cache hit (demo) |
| POST | `/simulate/miss?cache_key=...` | Simular cache miss (demo) |

## Ciclo de Autocrítica (Self-Critic Loop)

O módulo avalia periodicamente (a cada 5 min por omissão) se a taxa real de cache hits está a atingir o nível esperado:

```
Cache Warmer → Redis → Hit/Miss events
                            │
                     Self Critic (a cada 5 min)
                            │  hit_rate < threshold?
                            ▼
                    data/feedback.json  ← escreve crítica detalhada
                            │
                        AI Module  ← lê feedback
                            │
                    data/predictions.json  ← reescreve com estratégia corrigida
                            │
                    PredictionWatcher  ← deteta mudança → novo plano de cache
```

Se o desempenho for inferior ao esperado (ex: hit rate < 50%), o ficheiro `data/feedback.json` é gerado com:
- Regiões e serviços sub-performantes.
- Diagnóstico da diferença (gap) entre a hit rate real e a esperada.
- Recomendações automáticas para o AI (aumentar `cache_size_mb`, antecipar `lead_time_minutes` ou adicionar `content_keys`).
