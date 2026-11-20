#!/usr/bin/env python3
"""
Pré-aquecimento (provisioned concurrency) de AWS Lambda por zona da Europa.

Capacidade alvo = perfil histórico real (CloudWatch)
                  x efeito dos eventos ativos em cada PAÍS, ponderado pelo peso do país
                    no tráfego do deployment
                  + ajuste por feriados nacionais (usa o perfil de domingo)

Fontes de eventos (cada uma é opcional e falha isoladamente):
  futebol       football-data.org   FOOTBALL_API_KEY       gratuita (12 competições)
  predicthq     PredictHQ           PREDICTHQ_TOKEN        paga (14 dias de teste): concertos,
                                                           festivais, todos os desportos, com lotação
  ticketmaster  Ticketmaster        TICKETMASTER_API_KEY   gratuita: concertos (cobertura parcial,
                                                           sem lotação -> heurística de estádio)
  manual        ficheiro JSON       EVENTOS_MANUAIS        o que nenhuma API sabe: Black Friday,
                                                           campanhas, lançamentos, greves, eleições
  feriados      biblioteca `holidays` (offline, sem chave)

Outras variáveis: DRY_RUN ("1" por defeito: só mostra | "0": aplica), CACHE_DIR (/tmp).
Dependências: pip install boto3 requests holidays   (+ tzdata no Windows)
Permissões IAM: cloudwatch:GetMetricData e lambda:Get/Put/DeleteProvisionedConcurrencyConfig
Executar de 15 em 15 minutos (EventBridge Scheduler -> lambda_handler, ou cron -> main()).
"""
import datetime as dt
import json
import logging
import math
import os
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import boto3
import requests
from botocore.exceptions import BotoCoreError, ClientError

try:
    import holidays
except ImportError:  # sem a biblioteca, ignora feriados
    holidays = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("prewarm")

DRY_RUN = os.environ.get("DRY_RUN", "1") != "0"
CACHE_DIR = Path(os.environ.get("CACHE_DIR", "/tmp"))

# ----------------------------------------------------------------------------
# PARÂMETROS GERAIS. Os "efeitos" são palpites: calibra com os teus picos reais.
# ----------------------------------------------------------------------------
HEADROOM = 1.3          # margem de segurança sobre a previsão
LEAD_MIN = 20           # olha 20 min à frente (provisionar demora alguns minutos)
HISTERESE = 0.15        # ignora mudanças < 15% (evita oscilar)
MAX_BOOST, MIN_MULT = 4.0, 0.3   # limites do multiplicador final
EFEITO_MIN = 0.50       # eventos com |efeito| abaixo disto são ignorados
EFEITO_MAX = 3.0        # teto do efeito de um evento
DIA_PERFIL_FERIADO = 6  # em feriado usa o perfil de domingo (0=segunda ... 6=domingo)

# Sinal e escala por fonte. IMPORTANTE: depende do teu produto. Num serviço de media/
# apostas/streaming o tráfego SOBE durante jogos; noutros pode CAIR (as pessoas estão a ver).
# Mede e ajusta: 1.0 = sobe como definido, -0.5 = cai metade, 0 = desliga a fonte.
FATOR_FONTE = {"futebol": 1.0, "predicthq": 1.0, "ticketmaster": 1.0, "manual": 1.0}

PRE_EVENTO = dt.timedelta(minutes=30)
DURACAO_JOGO = dt.timedelta(hours=2, minutes=15)           # inclui intervalo e pós-jogo
DURACAO_ELIMINATORIA = dt.timedelta(hours=3, minutes=15)   # prolongamento/penáltis

# ----------------------------------------------------------------------------
# PAÍSES -> zona de audiência, peso, fuso horário, nomes (como a API de futebol os devolve).
# "peso" é um PROXY (população em milhões). Substitui pela % real do teu tráfego por país
# (logs do CloudFront/ALB): é o parâmetro que mais influencia o resultado.
# Zonas: oeste | central | norte (UK+Escandinávia+Bálticos) | sul_este | balcas
# ----------------------------------------------------------------------------
PAISES = {
    "PT": ("oeste", 10.4, "Europe/Lisbon", ["portugal"]),
    "ES": ("oeste", 48.0, "Europe/Madrid", ["spain"]),
    "FR": ("oeste", 68.0, "Europe/Paris", ["france"]),
    "BE": ("oeste", 11.8, "Europe/Brussels", ["belgium"]),
    "NL": ("oeste", 17.9, "Europe/Amsterdam", ["netherlands"]),
    "LU": ("oeste", 0.7, "Europe/Luxembourg", ["luxembourg"]),
    "DE": ("central", 84.0, "Europe/Berlin", ["germany"]),
    "AT": ("central", 9.1, "Europe/Vienna", ["austria"]),
    "CH": ("central", 8.8, "Europe/Zurich", ["switzerland"]),
    "PL": ("central", 37.0, "Europe/Warsaw", ["poland"]),
    "CZ": ("central", 10.9, "Europe/Prague", ["czech republic", "czechia"]),
    "SK": ("central", 5.4, "Europe/Bratislava", ["slovakia"]),
    "HU": ("central", 9.6, "Europe/Budapest", ["hungary"]),
    "GB": ("norte", 68.0, "Europe/London",
           ["england", "scotland", "wales", "northern ireland", "united kingdom"]),
    "IE": ("norte", 5.3, "Europe/Dublin", ["ireland", "republic of ireland"]),
    "SE": ("norte", 10.5, "Europe/Stockholm", ["sweden"]),
    "NO": ("norte", 5.5, "Europe/Oslo", ["norway"]),
    "DK": ("norte", 5.9, "Europe/Copenhagen", ["denmark"]),
    "FI": ("norte", 5.6, "Europe/Helsinki", ["finland"]),
    "IS": ("norte", 0.4, "Atlantic/Reykjavik", ["iceland"]),
    "EE": ("norte", 1.4, "Europe/Tallinn", ["estonia"]),
    "LV": ("norte", 1.9, "Europe/Riga", ["latvia"]),
    "LT": ("norte", 2.8, "Europe/Vilnius", ["lithuania"]),
    "IT": ("sul_este", 59.0, "Europe/Rome", ["italy"]),
    "GR": ("sul_este", 10.4, "Europe/Athens", ["greece"]),
    "RO": ("sul_este", 19.0, "Europe/Bucharest", ["romania"]),
    "BG": ("sul_este", 6.5, "Europe/Sofia", ["bulgaria"]),
    "TR": ("sul_este", 85.0, "Europe/Istanbul", ["turkey", "türkiye"]),
    "CY": ("sul_este", 1.3, "Asia/Nicosia", ["cyprus"]),
    "MT": ("sul_este", 0.5, "Europe/Malta", ["malta"]),
    "UA": ("sul_este", 38.0, "Europe/Kyiv", ["ukraine"]),
    "MD": ("sul_este", 2.6, "Europe/Chisinau", ["moldova"]),
    "RS": ("balcas", 6.7, "Europe/Belgrade", ["serbia"]),
    "HR": ("balcas", 3.9, "Europe/Zagreb", ["croatia"]),
    "BA": ("balcas", 3.2, "Europe/Sarajevo", ["bosnia-herzegovina", "bosnia and herzegovina"]),
    "ME": ("balcas", 0.6, "Europe/Podgorica", ["montenegro"]),
    "MK": ("balcas", 1.8, "Europe/Skopje", ["north macedonia", "macedonia"]),
    "AL": ("balcas", 2.8, "Europe/Tirane", ["albania"]),
    "SI": ("balcas", 2.1, "Europe/Ljubljana", ["slovenia"]),
    "XK": ("balcas", 1.8, "Europe/Belgrade", ["kosovo"]),
}
NOME_PARA_ISO = {n: iso for iso, (_, _, _, nomes) in PAISES.items() for n in nomes}

# Que deployment serve cada zona (várias zonas podem partilhar um deployment).
ZONA_DEPLOYMENT = {"oeste": "eu-oeste", "central": "eu-central", "norte": "eu-norte",
                   "sul_este": "eu-sul", "balcas": "eu-sul"}

# Onde o teu código corre. Só ganhas com isto se o tráfego de cada zona for mesmo
# encaminhado para o deployment certo (Route 53 por latência ou geolocalização).
DEPLOYMENTS = {
    "eu-oeste":   {"aws_region": "eu-west-3",    "function": "api", "alias": "live", "min_pc": 0, "max_pc": 200},
    "eu-central": {"aws_region": "eu-central-1", "function": "api", "alias": "live", "min_pc": 0, "max_pc": 200},
    "eu-norte":   {"aws_region": "eu-north-1",   "function": "api", "alias": "live", "min_pc": 0, "max_pc": 200},
    "eu-sul":     {"aws_region": "eu-south-1",   "function": "api", "alias": "live", "min_pc": 0, "max_pc": 200},
}


def _calcular_pesos():
    """deployment -> {pais: fração do tráfego desse deployment}."""
    por_dep = defaultdict(dict)
    for iso, (zona, peso, _, _) in PAISES.items():
        por_dep[ZONA_DEPLOYMENT[zona]][iso] = peso
    return {d: {iso: p / sum(ps.values()) for iso, p in ps.items()} for d, ps in por_dep.items()}


PESOS = _calcular_pesos()

# ----------------------------------------------------------------------------
# PARÂMETROS POR FONTE
# ----------------------------------------------------------------------------
# futebol: competição -> (efeito base, tipo). "liga": país da competição; "equipas": país de cada equipa
COMPETICOES = {
    "PL": (0.35, "liga"), "PD": (0.35, "liga"), "BL1": (0.35, "liga"), "SA": (0.35, "liga"),
    "FL1": (0.35, "liga"), "PPL": (0.35, "liga"), "DED": (0.30, "liga"),
    "CL": (0.80, "equipas"), "EC": (2.00, "equipas"), "WC": (2.00, "equipas"),
}
STAGE_MULT = {"FINAL": 2.0, "SEMI_FINALS": 1.6, "QUARTER_FINALS": 1.3, "LAST_16": 1.15}
ELIMINATORIAS = {"FINAL", "SEMI_FINALS", "QUARTER_FINALS", "LAST_16", "LAST_32",
                 "PLAYOFFS", "THIRD_PLACE"}
GRANDES = ("real madrid", "fc barcelona", "atlético", "benfica", "sporting clube de portugal",
           "fc porto", "manchester united", "manchester city", "liverpool", "arsenal",
           "chelsea", "tottenham", "bayern", "dortmund", "paris saint-germain", "juventus",
           "internazionale", "milan", "napoli", "ajax")   # confirma os nomes que a API devolve

# predicthq: efeito = PHQ_EFEITO_POR_100K x lotação/100k (ex.: 100k pessoas -> +0.5)
PHQ_CATEGORIAS = "sports,concerts,festivals,performing-arts,conferences,expos"
PHQ_RANK_MIN = 60
PHQ_EFEITO_POR_100K = 0.5

# ticketmaster: sem lotação na API -> só conta concertos em recintos com estes nomes
TM_RECINTOS_GRANDES = ("stadium", "stadion", "stade", "estadio", "estádio", "stadio",
                       "olympia", "wembley", "arena nacional")
TM_EFEITO_RECINTO_GRANDE = 0.5


# ----------------------------------------------------------------------------
# Utilitários
# ----------------------------------------------------------------------------
def chave(weekday, hora):
    return f"{weekday}-{hora}"


def _cache(nome, ttl_s, produzir):
    """Cache em JSON. Em Lambda o /tmp só persiste em containers quentes; em produção
    troca por S3/DynamoDB/SSM se quiseres cache partilhada."""
    f = CACHE_DIR / f"prewarm_{nome}.json"
    try:
        if time.time() - f.stat().st_mtime < ttl_s:
            return json.loads(f.read_text())
    except (OSError, ValueError):
        pass
    dados = produzir()
    try:
        f.write_text(json.dumps(dados))
    except OSError as e:
        log.warning("cache %s não gravada: %s", nome, e)
    return dados


def _parse_utc(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


@dataclass
class Evento:
    pais: str            # ISO alpha-2
    inicio: dt.datetime
    fim: dt.datetime
    efeito: float        # variação do tráfego desse país: 0.5 = +50%, negativo = quebra
    descricao: str
    fonte: str = ""


# ----------------------------------------------------------------------------
# Perfil histórico (CloudWatch)
# ----------------------------------------------------------------------------
def perfil_historico(dep, dias=28):
    """Concorrência típica por (dia da semana, hora UTC): lei de Little por janelas de 5 min,
    pico de cada hora, MEDIANA entre semanas (um jogo passado não inflaciona o perfil)."""
    cw = boto3.client("cloudwatch", region_name=dep["aws_region"])
    fim = dt.datetime.now(dt.timezone.utc).replace(minute=0, second=0, microsecond=0)
    ini = fim - dt.timedelta(days=dias)
    dim = [{"Name": "FunctionName", "Value": dep["function"]}]

    def q(i, metrica, stat):
        return {"Id": i, "ReturnData": True, "MetricStat": {
            "Metric": {"Namespace": "AWS/Lambda", "MetricName": metrica, "Dimensions": dim},
            "Period": 300, "Stat": stat}}

    series = defaultdict(dict)
    for page in cw.get_paginator("get_metric_data").paginate(
            MetricDataQueries=[q("inv", "Invocations", "Sum"), q("dur", "Duration", "Average")],
            StartTime=ini, EndTime=fim, ScanBy="TimestampAscending"):
        for r in page["MetricDataResults"]:
            for ts, v in zip(r["Timestamps"], r["Values"]):
                series[r["Id"]][ts] = v

    pico_hora = defaultdict(float)
    for ts, n in series["inv"].items():
        seg = series["dur"].get(ts, 100.0) / 1000.0
        k = (ts.date(), ts.hour)
        pico_hora[k] = max(pico_hora[k], n / 300.0 * seg)

    por_slot = defaultdict(list)
    h = ini
    while h < fim:  # todas as horas: as sem tráfego contam como 0
        por_slot[(h.weekday(), h.hour)].append(pico_hora.get((h.date(), h.hour), 0.0))
        h += dt.timedelta(hours=1)
    return {chave(*k): statistics.median(v) for k, v in por_slot.items()}


# ----------------------------------------------------------------------------
# Fonte: futebol (football-data.org)
# ----------------------------------------------------------------------------
FOOTBALL_API = "https://api.football-data.org/v4"


def _fb_get(path, **params):
    r = requests.get(f"{FOOTBALL_API}{path}",
                     headers={"X-Auth-Token": os.environ["FOOTBALL_API_KEY"]},
                     params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def _paises_das_equipas():
    """team_id -> nome do país, para Champions e seleções."""
    def obter():
        out = {}
        for code, (_, tipo) in COMPETICOES.items():
            if tipo != "equipas":
                continue
            try:
                for t in _fb_get(f"/competitions/{code}/teams")["teams"]:
                    out[str(t["id"])] = (t.get("area") or {}).get("name", "")
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code in (403, 404):
                    log.warning("competição %s indisponível (%s)", code, e.response.status_code)
                else:
                    raise
        return out
    return _cache("paises_equipas", 7 * 86400, obter)


def _jogos_brutos(agora):
    def obter():
        hoje = agora.date()
        return _fb_get("/matches", competitions=",".join(COMPETICOES),
                       dateFrom=(hoje - dt.timedelta(days=1)).isoformat(),
                       dateTo=(hoje + dt.timedelta(days=3)).isoformat())["matches"]
    return _cache("jogos", 3 * 3600, obter)


def eventos_futebol(agora):
    if not os.environ.get("FOOTBALL_API_KEY"):
        log.info("futebol: sem FOOTBALL_API_KEY, fonte desligada")
        return []
    paises_equipa = _paises_das_equipas()
    out = []
    for m in _jogos_brutos(agora):
        if m.get("status") not in ("SCHEDULED", "TIMED", "IN_PLAY", "PAUSED"):
            continue
        code = (m.get("competition") or {}).get("code")
        if code not in COMPETICOES:
            continue
        base, tipo = COMPETICOES[code]
        stage = m.get("stage")
        equipas = [m.get("homeTeam") or {}, m.get("awayTeam") or {}]
        nomes = [(t.get("name") or "").lower() for t in equipas]
        grandes = [any(g in n for g in GRANDES) for n in nomes]
        extra = 1.3 if all(grandes) else 1.0   # clássico/derby entre grandes

        por_pais = {}
        for t, grande in zip(equipas, grandes):
            nome_pais = (m.get("area") or {}).get("name", "") if tipo == "liga" \
                else paises_equipa.get(str(t.get("id")), "")
            iso = NOME_PARA_ISO.get(nome_pais.strip().lower())
            if not iso:
                if nome_pais:
                    log.warning("futebol: país sem mapeamento %r (jogo %s)", nome_pais, m.get("id"))
                continue
            ef = base * STAGE_MULT.get(stage, 1.0) * extra * (1.5 if grande else 1.0)
            por_pais[iso] = max(por_pais.get(iso, 0.0), ef)

        inicio = _parse_utc(m["utcDate"])
        dur = DURACAO_ELIMINATORIA if stage in ELIMINATORIAS else DURACAO_JOGO
        desc = (f"{equipas[0].get('name')} vs {equipas[1].get('name')} "
                f"[{code}{'/' + stage if stage else ''}]")
        for iso, ef in por_pais.items():
            if ef >= EFEITO_MIN:
                out.append(Evento(iso, inicio - PRE_EVENTO, inicio + dur,
                                  min(ef, EFEITO_MAX), desc, "futebol"))
    return out


# ----------------------------------------------------------------------------
# Fonte: PredictHQ (concertos, festivais, todos os desportos, com lotação estimada)
# ----------------------------------------------------------------------------
def eventos_predicthq(agora):
    token = os.environ.get("PREDICTHQ_TOKEN")
    if not token:
        log.info("predicthq: sem PREDICTHQ_TOKEN, fonte desligada")
        return []

    def obter():
        url = "https://api.predicthq.com/v1/events/"
        hoje = agora.date()
        params = {"category": PHQ_CATEGORIAS,
                  "country": ",".join(p for p in PAISES if p != "XK"),
                  "active.gte": (hoje - dt.timedelta(days=1)).isoformat(),
                  "active.lte": (hoje + dt.timedelta(days=3)).isoformat(),
                  "rank.gte": PHQ_RANK_MIN, "sort": "start", "limit": 200}
        out = []
        while url and len(out) < 2000:
            r = requests.get(url, headers={"Authorization": f"Bearer {token}"},
                             params=params, timeout=20)
            r.raise_for_status()
            j = r.json()
            out += j.get("results", [])
            url, params = j.get("next"), None   # o URL de "next" já traz os filtros
        return out

    out = []
    for ev in _cache("predicthq", 6 * 3600, obter):
        iso = (ev.get("country") or "").upper()
        if iso not in PAISES or not ev.get("start"):
            continue
        ef = PHQ_EFEITO_POR_100K * (ev.get("phq_attendance") or 0) / 100_000
        if ef < EFEITO_MIN:
            continue
        inicio = _parse_utc(ev["start"])
        fim = _parse_utc(ev["end"]) if ev.get("end") else inicio + DURACAO_JOGO
        out.append(Evento(iso, inicio - PRE_EVENTO, fim + PRE_EVENTO, min(ef, EFEITO_MAX),
                          f"{ev.get('title')} [{ev.get('category')}, ~{ev.get('phq_attendance')} pessoas]",
                          "predicthq"))
    return out


# ----------------------------------------------------------------------------
# Fonte: Ticketmaster (concertos; gratuita, cobertura parcial, sem lotação)
# ----------------------------------------------------------------------------
def eventos_ticketmaster(agora):
    key = os.environ.get("TICKETMASTER_API_KEY")
    if not key:
        log.info("ticketmaster: sem TICKETMASTER_API_KEY, fonte desligada")
        return []

    def obter():
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        out = []
        for iso in PAISES:
            if iso == "XK":
                continue
            try:
                r = requests.get("https://app.ticketmaster.com/discovery/v2/events.json", params={
                    "apikey": key, "countryCode": iso, "classificationName": "music",
                    "startDateTime": (agora - dt.timedelta(hours=12)).strftime(fmt),
                    "endDateTime": (agora + dt.timedelta(days=3)).strftime(fmt),
                    "size": 200, "sort": "date,asc"}, timeout=15)
                r.raise_for_status()
            except requests.RequestException as e:
                log.warning("ticketmaster %s: %s", iso, e)
                continue
            out += [dict(ev, _pais=iso) for ev in (r.json().get("_embedded") or {}).get("events", [])]
            time.sleep(0.25)   # limite de 5 pedidos/s
        return out

    out = []
    for ev in _cache("ticketmaster", 6 * 3600, obter):
        inicio_s = ((ev.get("dates") or {}).get("start") or {}).get("dateTime")
        venues = (ev.get("_embedded") or {}).get("venues") or [{}]
        recinto = (venues[0].get("name") or "").lower()
        if not inicio_s or not any(w in recinto for w in TM_RECINTOS_GRANDES):
            continue
        inicio = _parse_utc(inicio_s)
        out.append(Evento(ev["_pais"], inicio - dt.timedelta(hours=1), inicio + dt.timedelta(hours=4),
                          TM_EFEITO_RECINTO_GRANDE, f"{ev.get('name')} @ {venues[0].get('name')}",
                          "ticketmaster"))
    return out


# ----------------------------------------------------------------------------
# Fonte: eventos manuais (o que nenhuma API sabe)
# ----------------------------------------------------------------------------
def eventos_manuais(agora):
    """Ficheiro JSON: lista de {"descricao", "inicio", "fim", "efeito", e UM de:
    "paises": ["PT","ES"] | "zona": "oeste" | (nada = todos os países)}. Datas em ISO com Z."""
    f = Path(os.environ.get("EVENTOS_MANUAIS", "eventos_manuais.json"))
    if not f.exists():
        return []
    out = []
    for e in json.loads(f.read_text()):
        try:
            if e.get("paises"):
                isos = [p.upper() for p in e["paises"]]
            elif e.get("zona"):
                isos = [i for i, v in PAISES.items() if v[0] == e["zona"]]
            else:
                isos = list(PAISES)
            for iso in isos:
                if iso in PAISES:
                    out.append(Evento(iso, _parse_utc(e["inicio"]), _parse_utc(e["fim"]),
                                      float(e["efeito"]), e.get("descricao", "manual"), "manual"))
        except (KeyError, ValueError, TypeError) as err:
            log.warning("evento manual inválido %r: %s", e, err)
    return out


FONTES = {"futebol": eventos_futebol, "predicthq": eventos_predicthq,
          "ticketmaster": eventos_ticketmaster, "manual": eventos_manuais}


def recolher_eventos(agora):
    """Cada fonte falha isoladamente: se uma cair, as outras continuam."""
    todos = []
    for nome, fn in FONTES.items():
        try:
            evs = fn(agora)
        except (requests.RequestException, KeyError, ValueError, TypeError, OSError) as e:
            log.error("fonte %s falhou (%s): ignorada nesta execução", nome, e)
            continue
        for e in evs:
            e.efeito *= FATOR_FONTE.get(nome, 1.0)
        log.info("fonte %s: %d eventos", nome, len(evs))
        todos += evs
    return todos


# ----------------------------------------------------------------------------
# Feriados nacionais
# ----------------------------------------------------------------------------
@lru_cache(maxsize=None)
def _feriados(iso, ano):
    if holidays is None:
        return {}
    try:
        return holidays.country_holidays(iso, years=ano)
    except (NotImplementedError, KeyError):
        log.warning("feriados: país %s não suportado", iso)
        return {}


@lru_cache(maxsize=None)
def _fuso(nome):
    """Em sistemas sem tzdata (ex.: Windows: pip install tzdata) cai para UTC em vez de rebentar."""
    try:
        return ZoneInfo(nome)
    except ZoneInfoNotFoundError:
        log.warning("fuso %s não encontrado: uso UTC (instala o pacote tzdata)", nome)
        return dt.timezone.utc


def fracao_feriado(dep_nome, quando):
    """Fração do tráfego do deployment que está em feriado nacional (data LOCAL de cada país)."""
    h = 0.0
    for iso, peso in PESOS[dep_nome].items():
        local = quando.astimezone(_fuso(PAISES[iso][2])).date()
        if local in _feriados(iso, local.year):
            h += peso
    return h


def base_esperada(dep_nome, perfil, quando):
    normal = perfil.get(chave(quando.weekday(), quando.hour), 0.0)
    if quando.weekday() >= 5:   # fim de semana: o perfil já é o "dia livre"
        return normal
    h = fracao_feriado(dep_nome, quando)
    if h == 0:
        return normal
    feriado = perfil.get(chave(DIA_PERFIL_FERIADO, quando.hour), normal)
    return (1 - h) * normal + h * feriado


# ----------------------------------------------------------------------------
# Capacidade alvo
# ----------------------------------------------------------------------------
def multiplicador(dep_nome, eventos, quando):
    """1 + soma(peso do país no deployment x efeito do evento dominante nesse país).
    Só pesam os países com evento ativo: um jogo nos Balcãs não pré-aquece a Itália."""
    mult = 1.0
    for iso, peso in PESOS[dep_nome].items():
        ativos = [e.efeito for e in eventos if e.pais == iso and e.inicio <= quando <= e.fim]
        if ativos:
            mult += peso * max(ativos, key=abs)
    return max(MIN_MULT, min(MAX_BOOST, mult))


def alvo_pc(dep_nome, dep, perfil, eventos, agora):
    """Máximo da necessidade entre agora e agora+LEAD (não desce mesmo antes de uma subida)."""
    melhor = 0.0
    for minutos in range(0, LEAD_MIN + 1, 10):
        t = agora + dt.timedelta(minutes=minutos)
        melhor = max(melhor, base_esperada(dep_nome, perfil, t) * multiplicador(dep_nome, eventos, t))
    pc = math.ceil(melhor * HEADROOM)
    return max(dep["min_pc"], min(dep["max_pc"], pc))


# ----------------------------------------------------------------------------
# Aplicar na AWS
# ----------------------------------------------------------------------------
NAO_EXISTE = {"ProvisionedConcurrencyConfigNotFoundException", "ResourceNotFoundException"}


def _pc_atual(lam, dep):
    try:
        r = lam.get_provisioned_concurrency_config(FunctionName=dep["function"],
                                                   Qualifier=dep["alias"])
        return r.get("RequestedProvisionedConcurrentExecutions", 0)
    except ClientError as e:
        if e.response["Error"]["Code"] in NAO_EXISTE:
            return 0
        raise


def _vale_a_pena(atual, novo):
    if atual == novo:
        return False
    if atual == 0 or novo == 0:
        return True
    return abs(novo - atual) / atual >= HISTERESE


def aplicar(nome, dep, novo):
    lam = boto3.client("lambda", region_name=dep["aws_region"])
    atual = _pc_atual(lam, dep)
    if not _vale_a_pena(atual, novo):
        log.info("[%s] mantém %s (alvo %s)", nome, atual, novo)
        return
    log.info("[%s] provisioned concurrency %s -> %s%s", nome, atual, novo,
             "  (DRY_RUN)" if DRY_RUN else "")
    if DRY_RUN:
        return
    if novo == 0:
        try:
            lam.delete_provisioned_concurrency_config(FunctionName=dep["function"],
                                                      Qualifier=dep["alias"])
        except ClientError as e:
            if e.response["Error"]["Code"] not in NAO_EXISTE:
                raise
    else:
        lam.put_provisioned_concurrency_config(FunctionName=dep["function"],
                                               Qualifier=dep["alias"],
                                               ProvisionedConcurrentExecutions=novo)


# ----------------------------------------------------------------------------
def main():
    agora = dt.datetime.now(dt.timezone.utc)
    if holidays is None:
        log.warning("biblioteca 'holidays' não instalada: feriados ignorados")

    eventos = recolher_eventos(agora)
    for e in sorted(eventos, key=lambda x: x.inicio):
        if e.fim >= agora and e.inicio <= agora + dt.timedelta(hours=12):
            log.info("evento [%s] %+.2f %s -> %s | %s (%s)", e.pais, e.efeito,
                     e.inicio.strftime("%d/%m %H:%M"), e.fim.strftime("%H:%M UTC"),
                     e.descricao, e.fonte)

    for nome, dep in DEPLOYMENTS.items():
        try:
            perfil = _cache(f"perfil_{nome}", 86400, lambda d=dep: perfil_historico(d))
            if not any(perfil.values()):
                log.warning("[%s] sem histórico de tráfego: não altero nada", nome)
                continue
            fer = fracao_feriado(nome, agora)
            if fer:
                log.info("[%s] %.0f%% do tráfego está em feriado nacional hoje", nome, fer * 100)
            aplicar(nome, dep, alvo_pc(nome, dep, perfil, eventos, agora))
        except (ClientError, BotoCoreError) as e:
            log.error("[%s] falhou (%s): mantenho o estado atual", nome, e)


def lambda_handler(event=None, context=None):
    main()
    return {"dry_run": DRY_RUN}


if __name__ == "__main__":
    main()