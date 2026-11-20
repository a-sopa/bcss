# 🏆 Hackathon Picoas 2026 — Cloud Efficiency & Security with AI

Repositório unificado de soluções de engenharia, eficiência de custos e segurança avançada para infraestruturas Cloud utilizando Inteligência Artificial.

---

## 🚀 Módulos & Soluções Desenvolvidas

| Módulo | Área / Desafio | Descrição |
| :--- | :--- | :--- |
| **[cloud_honeypot_ai](file:///home/franc/Hackaton%20Picoas/hackaton-project/cloud_honeypot_ai)** | **Segurança & Eficiência Cloud + IA** | **"A Armadilha para Hackers" (Honeypot)** com análise comportamental por IA (MITRE ATT&CK), defesa ativa automatizada (AWS NACL / SG / iptables) e cofre forense criptográfico imutável (AES-256-GCM + SHA-256 blockchain + HMAC). |
| **[CacheManager](file:///home/franc/Hackaton%20Picoas/hackaton-project/CacheManager)** | **Eficiência de Rede & Latência** | Motor de cache preditivo inteligente com pré-aquecimento de rotas edge Redis e loop fechado de auto-crítica (*Self-Critic*). |
| **[scraper-ai](file:///home/franc/Hackaton%20Picoas/hackaton-project/scraper-ai)** | **Previsão de Picos & IA** | Scraper de eventos do mundo real com análise de impacto por LLM (Google Gemini) para alimentar a estratégia de pre-warming de cache. |
| **[JunctionX](file:///home/franc/Hackaton%20Picoas/hackaton-project/JunctionX)** | **Criptografia & Postura Cloud** | QuantumTrace: Auditoria estática e dinâmica de ativos criptográficos (KMS, TLS, CBOM CycloneDX 1.6) e prontidão pós-quântica (PQC). |

---

## ⚡ Quick Start — Cloud Honeypot AI Shield

Para testar ou demonstrar a solução de Honeypot e Defesa Cloud:

```bash
# 1. Demonstração Interativa Completa (End-to-End)
python3 -m cloud_honeypot_ai.run_honeypot demo

# 2. Iniciar Honeypots e Dashboard Web (http://localhost:8888)
python3 -m cloud_honeypot_ai.run_honeypot start

# 3. Executar a Suite de Testes (35 testes, 100% OK)
python3 -m unittest discover -s cloud_honeypot_ai/tests -v
```
