#!/usr/bin/env python3
"""
Architectural Benchmark & Solution Comparator
Evaluates `scraper-ai` (User's Solution) vs `CacheManager` (Colleague's Solution)
across key Hackathon and Production Engineering dimensions.
"""
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRAPER_DIR = REPO_ROOT / "scraper-ai"
CACHE_DIR = REPO_ROOT / "CacheManager"
HONEYPOT_DIR = REPO_ROOT / "cloud_honeypot_ai"


def count_code_metrics(directory: Path):
    py_files = list(directory.glob("**/*.py"))
    total_lines = 0
    code_lines = 0
    comment_lines = 0
    blank_lines = 0

    for f in py_files:
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
            total_lines += len(lines)
            for line in lines:
                s = line.strip()
                if not s:
                    blank_lines += 1
                elif s.startswith("#"):
                    comment_lines += 1
                else:
                    code_lines += 1
        except Exception:
            pass

    return {
        "files_count": len(py_files),
        "total_lines": total_lines,
        "code_lines": code_lines,
        "comment_lines": comment_lines,
        "blank_lines": blank_lines,
    }


def run_comparison():
    scraper_metrics = count_code_metrics(SCRAPER_DIR)
    preheat_dir = REPO_ROOT / "server-preheat"
    if preheat_dir.exists():
        pm = count_code_metrics(preheat_dir)
        scraper_metrics["files_count"] += pm["files_count"]
        scraper_metrics["total_lines"] += pm["total_lines"]
        scraper_metrics["code_lines"] += pm["code_lines"]
        scraper_metrics["comment_lines"] += pm["comment_lines"]
        scraper_metrics["blank_lines"] += pm["blank_lines"]

    cache_metrics = count_code_metrics(CACHE_DIR)
    honeypot_metrics = count_code_metrics(HONEYPOT_DIR) if HONEYPOT_DIR.exists() else None

    comparison_matrix = {
        "DIMENSION": [
            "1. Real-World Data Ingestion",
            "2. AI Context Reasoning (LLM)",
            "3. Statistical Baseline & Time-series",
            "4. Cloud Scaling (Provisioned Concurrency)",
            "5. Active Runtime Warm-up (Probes)",
            "6. Redis Cache Operations & Pipelines",
            "7. Dynamic Priority Scoring",
            "8. Production REST API & Swagger",
            "9. Closed-Loop Self-Criticism",
            "10. Docker Containerization",
        ],
        "SCRAPER_AI (Tua Solucao)": [
            "⭐⭐⭐⭐⭐ (Futebol, Ticketmaster, PredictHQ, Manual, Feriados)",
            "⭐⭐⭐⭐⭐ (Google Gemini 2.5 Flash + Heurística Fallback)",
            "⭐⭐⭐⭐⭐ (Mediana CloudWatch 28d, 168h slots, Demografia)",
            "⭐⭐⭐⭐⭐ (AWS Lambda API com margem 30% e histerese 15%)",
            "⭐⭐⭐⭐⭐ (ThreadPoolExecutor com pedidos concorrentes)",
            "⭐ (Não toca em Redis - gera diretivas)",
            "⭐⭐ (Multiplicador de tráfego regional)",
            "⭐ (Script / Lambda Handler - sem API REST)",
            "⭐⭐⭐ (Consome feedback do CacheManager)",
            "⭐⭐ (Focado em execução CLI / Lambda)",
        ],
        "CACHE_MANAGER (Colega)": [
            "⭐ (Não tem conectores externos - precisa de JSON)",
            "⭐ (Não interage diretamente com LLM - consome o JSON)",
            "⭐ (Sem modelação estatística diurna)",
            "⭐ (Não gere infraestrutura de servidores cloud)",
            "⭐ (Não aquece runtime/DB pool)",
            "⭐⭐⭐⭐⭐ (Redis async pipelines, HSET, EXPIRE, O(1) metrics)",
            "⭐⭐⭐⭐⭐ (Score multi-fator: Confiança x Carga x Urgência)",
            "⭐⭐⭐⭐⭐ (FastAPI completo com 10 endpoints + Docs)",
            "⭐⭐⭐⭐⭐ (Motor SelfCritic com cálculo de gap e feedback)",
            "⭐⭐⭐⭐⭐ (Docker Compose com Redis e FastAPI prontos)",
        ],
    }

    print("=" * 80)
    print(" 📊 BENCHMARK COMPARATIVO: SCRAPER-AI vs CACHEMANAGER")
    print("=" * 80)
    print(f"\n[MÉTRICAS DE CÓDIGO]")
    print(f"  • scraper-ai + server-preheat: {scraper_metrics['files_count']} ficheiros Python | {scraper_metrics['code_lines']} linhas de código ({scraper_metrics['total_lines']} totais)")
    print(f"  • CacheManager (Redis Cache): {cache_metrics['files_count']} ficheiros Python | {cache_metrics['code_lines']} linhas de código ({cache_metrics['total_lines']} totais)")
    if honeypot_metrics:
        print(f"  • cloud_honeypot_ai (Shield):  {honeypot_metrics['files_count']} ficheiros Python | {honeypot_metrics['code_lines']} linhas de código ({honeypot_metrics['total_lines']} totais)")

    print(f"\n[MATRIZ DE CAPACIDADES FUNCIONAIS]")
    for dim, mine, theirs in zip(comparison_matrix["DIMENSION"], comparison_matrix["SCRAPER_AI (Tua Solucao)"], comparison_matrix["CACHE_MANAGER (Colega)"]):
        print(f"\n{dim}:")
        print(f"   ▶ Tua Solução (scraper-ai):  {mine}")
        print(f"   ▶ Colega (CacheManager):     {theirs}")

    print("\n" + "=" * 80)
    print(" 🏆 VEREDITO TÉCNICO")
    print("=" * 80)
    print("""
1. QUAL É MELHOR?
   Nenhuma das duas é 'melhor' no vácuo, porque resolvem METADES OPOSTAS do mesmo problema:
   - A TUA solução é superior em: Inteligência Externa, Data Scraping, Modelação Matemática, IA Semântica (Gemini) e Dimensionamento Cloud (AWS Lambda).
   - A solução do TEU COLEGA é superior em: Engenharia de Software, APIs REST, Operações de Memória (Redis), Métricas em Tempo Real e Loop de Autocrítica.

2. O 'TRUQUE' PARA VENCER O HACKATHON:
   Se apresentarem uma contra a outra, ambas têm falhas óbvias:
   - Apresentar só a tua: 'De que serve prever se ninguém carrega a cache no Redis?'
   - Apresentar só a dele: 'De que serve uma cache inteligente se as previsões são inventadas à mão num ficheiro JSON?'

   A verdadeira nota máxima (10/10) é apresentá-las UNIDAS através do bridge:
   'Criámos um sistema de Closed-Loop Autonomous Infrastructure onde o scraper-ai prevê
   com Gemini, o CacheManager pré-aquece o Redis e audita o tráfego, e o Self-Critic retroalimenta a IA.'
""")
    print("=" * 80)


if __name__ == "__main__":
    run_comparison()
