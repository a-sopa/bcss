#!/usr/bin/env python3
"""
Módulo de Integração com Google Gemini (LLM) para Análise Inteligente de Eventos
e Geração de Diretivas para o Cache Manager do Servidor.

Suporta:
- Chamada direta via API REST do Gemini (sem necessidade de SDKs pesados adicionais).
- Modo Heurístico Automático (Fallback) se GEMINI_API_KEY não estiver definida ou falhar,
  garantindo que o sistema é 100% funcional imediatamente.
- Exportação de diretivas de cache estruturadas para o futuro `cache_manager`.
"""
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger("prewarm.gemini")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip()
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models"


def is_gemini_active() -> bool:
    """Verifica se a chave da API do Gemini está configurada."""
    return bool(GEMINI_API_KEY)


def _analise_heuristica_fallback(evento: Any) -> Dict[str, Any]:
    """
    Fallback heurístico inteligente para quando a API do Gemini não estiver configurada
    ou ocorrer erro de rede. Garante que o pipeline nunca quebra e continua funcional.
    """
    desc = getattr(evento, "descricao", "").lower()
    pais = getattr(evento, "pais", "")
    efeito_base = float(getattr(evento, "efeito", 0.5))

    categoria = "outro"
    padrao = "alta_sustentada"
    estrategia = "padrao"
    ttl = 900
    rotas = ["/api/v1/feed", "/api/v1/status"]
    confianca = 0.75
    razao = "Análise heurística de fallback baseada no tipo de evento."

    if any(k in desc for k in ["black friday", "cyber monday", "campanha", "promo", "lançamento"]):
        categoria = "comercial"
        padrao = "alta_sustentada"
        estrategia = "pre_cache_agressivo"
        ttl = 3600
        rotas = ["/api/v1/produtos", "/api/v1/catalogo", "/api/v1/promocoes", "/api/v1/checkout"]
        confianca = 0.90
        razao = "Evento comercial de grande volume; recomenda-se pré-aquecimento agressivo de catálogo."
    elif any(k in desc for k in ["vs", "cl", "pl", "derby", "futebol", "champions", "taça", "cup"]):
        categoria = "desporto"
        padrao = "pico_pre_evento"
        estrategia = "stale_while_revalidate"
        ttl = 300
        rotas = ["/api/v1/live", "/api/v1/placar", "/api/v1/stream", "/api/v1/noticias"]
        confianca = 0.85
        razao = "Evento desportivo gera picos concentrados imediatamente antes e ao intervalo."
    elif any(k in desc for k in ["concert", "concerto", "festival", "show", "stadium", "arena"]):
        categoria = "musica_cultura"
        padrao = "pico_pos_evento"
        estrategia = "pre_cache_agressivo"
        ttl = 1800
        rotas = ["/api/v1/bilhetes", "/api/v1/recintos", "/api/v1/agenda"]
        confianca = 0.80
        razao = "Espetáculo cultural ao vivo; picos de consulta de acessos e ingressos."
    elif any(k in desc for k in ["greve", "strike", "protesto", "tempestade", "alerta"]):
        categoria = "interrupcao_regional"
        padrao = "alta_sustentada"
        estrategia = "bypass_dinamico"
        ttl = 120
        rotas = ["/api/v1/alertas", "/api/v1/transportes", "/api/v1/noticias"]
        confianca = 0.85
        razao = "Interrupção de serviços públicos; forte aumento de pedidos de informação em tempo real."

    return {
        "categoria": categoria,
        "padrao_trafego": padrao,
        "efeito_ajustado": round(efeito_base, 2),
        "confianca": confianca,
        "razao": razao,
        "estrategia_cache": estrategia,
        "ttl_segundos_recomendado": ttl,
        "rotas_pre_aquecer": rotas,
        "analisado_por": "heuristica_local",
    }


def analisar_eventos_com_gemini(eventos: List[Any]) -> List[Dict[str, Any]]:
    """
    Submete a lista de eventos à API do Gemini para enriquecimento semântico,
    avaliação do comportamento de tráfego e diretivas de cache.

    Se GEMINI_API_KEY não estiver definida, usa fallback heurístico transparente.
    """
    if not eventos:
        return []

    if not GEMINI_API_KEY:
        log.info("Gemini AI: GEMINI_API_KEY não definida. A usar análise heurística interna (defina GEMINI_API_KEY para ativar LLM).")
        resultados = []
        for ev in eventos:
            analise = _analise_heuristica_fallback(ev)
            analise["evento_descricao"] = ev.descricao
            analise["pais"] = ev.pais
            analise["inicio_utc"] = ev.inicio.isoformat()
            analise["fim_utc"] = ev.fim.isoformat()
            analise["fonte"] = getattr(ev, "fonte", "desconhecida")
            resultados.append(analise)
        return resultados

    # Preparar payload para o Gemini
    eventos_simplificados = [
        {
            "id": idx,
            "descricao": ev.descricao,
            "pais": ev.pais,
            "inicio_utc": ev.inicio.isoformat(),
            "fim_utc": ev.fim.isoformat(),
            "efeito_estimado_inicial": ev.efeito,
            "fonte": getattr(ev, "fonte", "desconhecida"),
        }
        for idx, ev in enumerate(eventos)
    ]

    prompt = f"""
Tu és um especialista em infraestrutura cloud, dimensionamento de servidores e estratégias de cache HTTP / Redis para serviços digitais na Europa.

Analisa a seguinte lista de eventos e avalia o impacto real no tráfego de servidores e na gestão de cache:
{json.dumps(eventos_simplificados, indent=2, ensure_ascii=False)}

Para CADA evento (mantendo o respetivo 'id'), devolve um objeto JSON com:
- "id": id do evento
- "categoria": uma de ["desporto", "musica_cultura", "comercial", "interrupcao_regional", "politica_social", "outro"]
- "padrao_trafego": um de ["pico_pre_evento", "queda_durante_evento", "pico_pos_evento", "alta_sustentada"]
- "efeito_ajustado": número float entre -1.0 e 3.0 (ex: 0.8 = +80% tráfego, -0.4 = quebra de 40%)
- "confianca": float entre 0.0 e 1.0
- "razao": explicação concisa (máximo 1 frase em português)
- "estrategia_cache": uma de ["pre_cache_agressivo", "stale_while_revalidate", "bypass_dinamico", "padrao"]
- "ttl_segundos_recomendado": inteiro (ex: 120, 300, 1800, 3600)
- "rotas_pre_aquecer": lista com 2 a 4 endpoints URL típicos recomendados para pré-aquecer na cache

Devolve uma lista de objetos JSON correspondente.
"""

    endpoint = f"{GEMINI_API_URL}/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.2,
        },
    }

    try:
        log.info("Gemini AI: a analisar %d eventos via modelo %s...", len(eventos), GEMINI_MODEL)
        resp = requests.post(endpoint, headers=headers, json=body, timeout=25)
        resp.raise_for_status()
        data = resp.json()

        raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
        itens_ia = json.loads(raw_text)

        # Mapear de volta por ID
        mapa_ia = {item["id"]: item for item in itens_ia if "id" in item}

        resultados = []
        for idx, ev in enumerate(eventos):
            ia = mapa_ia.get(idx)
            if not ia:
                ia = _analise_heuristica_fallback(ev)
            else:
                ia["analisado_por"] = f"gemini_{GEMINI_MODEL}"

            ia["evento_descricao"] = ev.descricao
            ia["pais"] = ev.pais
            ia["inicio_utc"] = ev.inicio.isoformat()
            ia["fim_utc"] = ev.fim.isoformat()
            ia["fonte"] = getattr(ev, "fonte", "desconhecida")
            resultados.append(ia)

        log.info("Gemini AI: análise de eventos concluída com sucesso.")
        return resultados

    except Exception as e:
        log.warning("Gemini AI falhou (%s). A recorrer à heurística de fallback.", e)
        resultados = []
        for ev in eventos:
            analise = _analise_heuristica_fallback(ev)
            analise["evento_descricao"] = ev.descricao
            analise["pais"] = ev.pais
            analise["inicio_utc"] = ev.inicio.isoformat()
            analise["fim_utc"] = ev.fim.isoformat()
            analise["fonte"] = getattr(ev, "fonte", "desconhecida")
            resultados.append(analise)
        return resultados


def exportar_para_cache_manager(
    caminho_saida: os.PathLike,
    agora: Any,
    deployments_resultado: Dict[str, Any],
    eventos_analisados: List[Dict[str, Any]],
    dry_run: bool = True,
) -> None:
    """
    Exporta a estrutura final em formato JSON padronizado para consumo
    pelo futuro cache_manager.
    """
    diretivas_por_zona = {}

    for nome_dep, dados_dep in deployments_resultado.items():
        # Encontrar eventos relevantes para esta zona
        eventos_zona = [
            ev for ev in eventos_analisados
            if ev.get("pais") in dados_dep.get("paises_cobertos", [])
        ]

        # Determinar estratégia dominante de cache para a zona
        estrategia_dominante = "padrao"
        ttl_recomendado = 900
        rotas_a_aquecer = set()

        if dados_dep.get("multiplicador", 1.0) >= 1.5:
            estrategia_dominante = "pre_cache_agressivo"
            ttl_recomendado = 3600
        elif dados_dep.get("multiplicador", 1.0) >= 1.2:
            estrategia_dominante = "stale_while_revalidate"
            ttl_recomendado = 1800

        for ez in eventos_zona:
            for r in ez.get("rotas_pre_aquecer", []):
                rotas_a_aquecer.add(r)
            if ez.get("estrategia_cache") == "pre_cache_agressivo":
                estrategia_dominante = "pre_cache_agressivo"
                ttl_recomendado = max(ttl_recomendado, ez.get("ttl_segundos_recomendado", 1800))

        diretivas_por_zona[nome_dep] = {
            "aws_region": dados_dep.get("aws_region"),
            "function": dados_dep.get("function"),
            "status_preaquecimento": "pico_previsto" if dados_dep.get("multiplicador", 1.0) > 1.2 else "normal",
            "multiplicador_trafego": dados_dep.get("multiplicador", 1.0),
            "capacidade_alvo_lambda": dados_dep.get("alvo_pc", 0),
            "capacidade_atual_lambda": dados_dep.get("atual_pc", 0),
            "diretiva_cache": {
                "estrategia_recomendada": estrategia_dominante,
                "ttl_segundos_recomendado": ttl_recomendado,
                "stale_while_revalidate_segundos": 120,
                "rotas_pre_carregar": sorted(list(rotas_a_aquecer)),
                "prioridade_evicao": "proteger_rotas_em_pico",
            },
        }

    documento_cache = {
        "timestamp_utc": agora.isoformat(),
        "versao_gerador": "2.0-gemini-ai",
        "dry_run": dry_run,
        "ia_status": {
            "gemini_ativo": is_gemini_active(),
            "modelo": GEMINI_MODEL if is_gemini_active() else "fallback_heuristico",
        },
        "deployments": diretivas_por_zona,
        "eventos_processados": eventos_analisados,
        "instrucoes_cache_manager": {
            "acao_sugerida": "aquecer_cache_nas_zonas_em_pico",
            "tempo_antecedencia_minutos": 20,
            "descricao": "Dados prontos para consumo por cache_manager HTTP/Redis.",
        },
    }

    try:
        caminho = Path(caminho_saida)
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(json.dumps(documento_cache, indent=2, ensure_ascii=False))
        log.info("Cache Manager: dados gravados com sucesso em %s", caminho)
    except OSError as e:
        log.error("Cache Manager: erro ao gravar ficheiro JSON (%s)", e)
