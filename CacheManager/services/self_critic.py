"""
Self-Critic Service — avalia a performance real da cache e,
caso a taxa de hits esteja abaixo do esperado, escreve um
ficheiro de feedback para o AI repensar a estratégia.

Fluxo:
  1. Corre a cada CRITIC_INTERVAL_SECONDS (padrão: 5 min)
  2. Para cada plano HOT, compara hit_rate real vs. limiar esperado
  3. Se hit_rate < threshold → escreve data/feedback.json
  4. O AI lê o feedback e gera um novo predictions.json com ajustes
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, field, asdict

from models.cache_plan import CachePlan, WarmingStatus
from config import settings

logger = logging.getLogger(__name__)


# ─── Thresholds ──────────────────────────────────────────────────────────────

# Hit rate mínima esperada — abaixo disto o sistema entra em autocrítica.
# Para um plano com confidence=0.95, esperamos pelo menos 0.95 * HIT_RATE_FACTOR.
HIT_RATE_FACTOR = 0.75          # 75% da confiança do AI como limiar
MIN_REQUESTS_TO_EVALUATE = 5    # Limiar ágil para testes, demos e produção
FEEDBACK_FILE: Path = settings.predictions_file.parent / "feedback.json"


# ─── Dataclasses de resultado ────────────────────────────────────────────────

@dataclass
class ServiceCritique:
    service: str
    platform: str
    actual_hit_rate: float
    expected_hit_rate: float
    total_requests: int
    hits: int
    misses: int
    verdict: str          # "ok" | "underperforming" | "insufficient_data"
    suggestion: str


@dataclass
class RegionCritique:
    region: str
    event_name: str
    prediction_id: str
    overall_hit_rate: float
    expected_hit_rate: float
    total_requests: int
    allocated_mb: float
    passed: bool
    services: list[ServiceCritique] = field(default_factory=list)
    recommendation: str = ""


@dataclass
class CritiqueReport:
    evaluated_at: str
    overall_passed: bool
    regions_evaluated: int
    regions_failed: int
    critiques: list[RegionCritique] = field(default_factory=list)
    feedback_written: bool = False


# ─── Self Critic ─────────────────────────────────────────────────────────────

class SelfCritic:
    """
    Avalia a performance da cache e escreve feedback para o AI
    quando os resultados ficam aquém do esperado.
    """

    def __init__(self):
        self._last_critique: CritiqueReport | None = None

    @property
    def last_critique(self) -> CritiqueReport | None:
        return self._last_critique

    def evaluate(self, plan: CachePlan, min_requests: int | None = None) -> CritiqueReport:
        """
        Avalia todos os planos HOT e verifica se a hit rate está
        dentro do esperado face à confiança original do AI.
        """
        req_threshold = min_requests if min_requests is not None else MIN_REQUESTS_TO_EVALUATE
        report = CritiqueReport(
            evaluated_at=datetime.now(timezone.utc).isoformat(),
            overall_passed=True,
            regions_evaluated=0,
            regions_failed=0,
        )

        for region, region_plans in plan.region_plans.items():
            for rplan in region_plans:
                # Só avaliar planos que estão ativos (HOT ou COOLING)
                if rplan.status not in (WarmingStatus.HOT, WarmingStatus.COOLING):
                    continue

                total_requests = rplan.total_hits + rplan.total_misses
                if total_requests < req_threshold:
                    logger.debug(
                        f"[{region}] '{rplan.event_name}': apenas {total_requests} pedidos "
                        f"(mínimo {req_threshold} para avaliar)"
                    )
                    continue

                report.regions_evaluated += 1

                # Obter confiança original do plano (guardada como prioridade máxima)
                max_priority = max((e.priority for e in rplan.entries), default=0.8)
                # Normalizar para 0-1 (a prioridade pode ser > 1 devido ao multiplicador)
                raw_confidence = min(max_priority / 10.0, 1.0)
                expected_hit_rate = max(raw_confidence * HIT_RATE_FACTOR, 0.5)

                actual_hit_rate = rplan.overall_hit_rate

                critique = RegionCritique(
                    region=region,
                    event_name=rplan.event_name,
                    prediction_id=rplan.prediction_id,
                    overall_hit_rate=round(actual_hit_rate, 4),
                    expected_hit_rate=round(expected_hit_rate, 4),
                    total_requests=total_requests,
                    allocated_mb=rplan.total_allocated_mb,
                    passed=True,
                )

                # Avaliar cada serviço individualmente
                for entry in rplan.entries:
                    svc_requests = entry.hit_count + entry.miss_count
                    if svc_requests == 0:
                        verdict = "insufficient_data"
                        suggestion = "Sem dados suficientes para avaliar."
                    elif entry.hit_rate >= expected_hit_rate:
                        verdict = "ok"
                        suggestion = "Performance dentro do esperado."
                    else:
                        verdict = "underperforming"
                        gap = expected_hit_rate - entry.hit_rate
                        suggestion = self._generate_suggestion(entry.service_name, gap, entry.size_bytes)

                    critique.services.append(ServiceCritique(
                        service=entry.service_name,
                        platform=entry.platform,
                        actual_hit_rate=round(entry.hit_rate, 4),
                        expected_hit_rate=round(expected_hit_rate, 4),
                        total_requests=svc_requests,
                        hits=entry.hit_count,
                        misses=entry.miss_count,
                        verdict=verdict,
                        suggestion=suggestion,
                    ))

                # A região só passa se o hit rate global for suficiente E se nenhum serviço essencial estiver em falha
                has_underperforming = any(s.verdict == "underperforming" for s in critique.services)
                passed = (actual_hit_rate >= expected_hit_rate) and not has_underperforming
                critique.passed = passed

                # Recomendação global para a região
                if not passed:
                    report.regions_failed += 1
                    report.overall_passed = False
                    critique.recommendation = self._generate_region_recommendation(
                        critique, expected_hit_rate
                    )
                    logger.warning(
                        f"⚠️  Autocrítica [{region}] '{rplan.event_name}': "
                        f"hit_rate={actual_hit_rate:.1%} < esperado={expected_hit_rate:.1%} "
                        f"→ a pedir revisão ao AI"
                    )
                else:
                    critique.recommendation = "Cache a performar conforme esperado. Sem ação necessária."
                    logger.info(
                        f"✅ Autocrítica [{region}] '{rplan.event_name}': "
                        f"hit_rate={actual_hit_rate:.1%} ≥ esperado={expected_hit_rate:.1%} — OK"
                    )

                report.critiques.append(critique)

        # Se nenhuma região tinha tráfego para avaliar, não fingir aprovação
        if report.regions_evaluated == 0:
            report.overall_passed = False

        # Se alguma região falhou, escrever feedback para o AI
        if report.regions_failed > 0:
            self._write_feedback(report)
            report.feedback_written = True

        self._last_critique = report
        return report

    def _generate_suggestion(self, service: str, gap: float, size_bytes: int) -> str:
        """Gera uma sugestão específica baseada no tipo de falha."""
        size_mb = size_bytes / (1024 * 1024)
        if gap > 0.3:
            return (
                f"Hit rate muito abaixo do esperado (gap={gap:.1%}). "
                f"Sugestão: aumentar cache_size_mb de {size_mb:.0f} MB para {size_mb * 2:.0f} MB "
                f"e aumentar lead_time_minutes para pre-aquecer mais cedo."
            )
        elif gap > 0.1:
            return (
                f"Hit rate moderadamente baixa (gap={gap:.1%}). "
                f"Sugestão: aumentar cache_size_mb para {size_mb * 1.5:.0f} MB."
            )
        else:
            return f"Hit rate ligeiramente abaixo (gap={gap:.1%}). Monitorizar."

    def _generate_region_recommendation(
        self, critique: RegionCritique, expected: float
    ) -> str:
        gap = expected - critique.overall_hit_rate
        underperforming = [s for s in critique.services if s.verdict == "underperforming"]
        services_str = ", ".join(set(s.service for s in underperforming))
        return (
            f"Região '{critique.region}' com hit_rate={critique.overall_hit_rate:.1%} "
            f"(esperado ≥ {expected:.1%}, gap={gap:.1%}). "
            f"Serviços problemáticos: {services_str}. "
            f"Recomenda-se: aumentar cache_size_mb, aumentar lead_time_minutes "
            f"ou adicionar mais content_keys específicos para pre-aquecimento."
        )

    def _write_feedback(self, report: CritiqueReport):
        """
        Escreve o relatório de autocrítica no ficheiro feedback.json
        para que o AI module possa ler e reajustar as previsões.
        """
        feedback = {
            "type": "cache_performance_feedback",
            "evaluated_at": report.evaluated_at,
            "summary": {
                "regions_evaluated": report.regions_evaluated,
                "regions_failed": report.regions_failed,
                "overall_passed": report.overall_passed,
            },
            "failed_regions": [
                {
                    "region": c.region,
                    "prediction_id": c.prediction_id,
                    "event_name": c.event_name,
                    "actual_hit_rate": c.overall_hit_rate,
                    "expected_hit_rate": c.expected_hit_rate,
                    "total_requests": c.total_requests,
                    "current_allocated_mb": c.allocated_mb,
                    "recommendation": c.recommendation,
                    "underperforming_services": [
                        {
                            "service": s.service,
                            "platform": s.platform,
                            "actual_hit_rate": s.actual_hit_rate,
                            "expected_hit_rate": s.expected_hit_rate,
                            "hits": s.hits,
                            "misses": s.misses,
                            "suggestion": s.suggestion,
                        }
                        for s in c.services
                        if s.verdict == "underperforming"
                    ],
                }
                for c in report.critiques
                if not c.passed
            ],
            "instruction_to_ai": (
                "A cache está a performar abaixo do esperado nas regiões listadas. "
                "Por favor, revê as previsões e ajusta: aumenta cache_size_mb dos serviços "
                "problemáticos, aumenta lead_time_minutes para pre-aquecer mais cedo, "
                "e/ou adiciona content_keys específicos. Gera um novo predictions.json."
            ),
        }

        FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
        FEEDBACK_FILE.write_text(json.dumps(feedback, indent=2, ensure_ascii=False))
        logger.info(f"📝 Feedback escrito para o AI em: {FEEDBACK_FILE}")
