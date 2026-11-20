#!/usr/bin/env python3
"""
AWS Lambda Provisioned Concurrency Pre-Warming & Server Cache Directives Engine
across European zones, powered by Google Gemini AI event analysis.

Target Capacity = Historical Profile (CloudWatch / Realistic Baseline)
                  x Country Event Effect (analyzed by Gemini AI), weighted by country share
                  + National Holiday adjustment (Sunday profile fallback)

Event Sources:
  football      football-data.org   FOOTBALL_API_KEY       Free tier (12 competitions)
  predicthq     PredictHQ           PREDICTHQ_TOKEN        Paid (14-day trial): concerts, sports
  ticketmaster  Ticketmaster        TICKETMASTER_API_KEY   Free tier: concerts
  manual        JSON file           MANUAL_EVENTS          Unstructured promotions, campaigns, launches
  holidays      `holidays` package  (Offline, no key)
  gemini        Google Gemini AI    GEMINI_API_KEY         Semantic analysis and caching strategy

Outputs to: cache_manager_feed.json (ready for downstream cache manager)
"""
import datetime as dt
import json
import logging
import math
import os
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Ensure scraper-ai directory is in sys.path for local module resolution
SCRAPER_DIR = Path(__file__).resolve().parent
if str(SCRAPER_DIR) not in sys.path:
    sys.path.insert(0, str(SCRAPER_DIR))

import requests

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:
    boto3 = None
    BotoCoreError = Exception
    ClientError = Exception

try:
    import holidays
except ImportError:
    holidays = None

# Gemini AI integration
from gemini_analyzer import (
    analyze_events_with_gemini,
    export_to_cache_manager,
    is_gemini_active,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("prewarm")

DRY_RUN = os.environ.get("DRY_RUN", "1") != "0"
CACHE_DIR = Path(os.environ.get("CACHE_DIR", "/tmp"))

# ----------------------------------------------------------------------------
# General Tuning Parameters
# ----------------------------------------------------------------------------
HEADROOM = 1.3          # 30% safety headroom above forecasted concurrency
LEAD_MIN = 20           # Look-ahead window in minutes (provisioning takes a few minutes)
HYSTERESIS = 0.15       # Ignore changes under 15% to prevent oscillation
MAX_BOOST, MIN_MULT = 4.0, 0.3
MIN_EFFECT = 0.50       # Ignore events below this absolute effect
MAX_EFFECT = 3.0        # Cap maximum individual event effect
HOLIDAY_PROFILE_DAY = 6 # Use Sunday profile (6) during national holidays

SOURCE_WEIGHTS = {"football": 1.0, "predicthq": 1.0, "ticketmaster": 1.0, "manual": 1.0}

PRE_EVENT_WINDOW = dt.timedelta(minutes=30)
REGULAR_MATCH_DURATION = dt.timedelta(hours=2, minutes=15)
KNOCKOUT_MATCH_DURATION = dt.timedelta(hours=3, minutes=15)

# ----------------------------------------------------------------------------
# Countries: Zone, Population Weight, Timezone, Aliases
# ----------------------------------------------------------------------------
COUNTRIES = {
    "PT": ("west", 10.4, "Europe/Lisbon", ["portugal"]),
    "ES": ("west", 48.0, "Europe/Madrid", ["spain"]),
    "FR": ("west", 68.0, "Europe/Paris", ["france"]),
    "BE": ("west", 11.8, "Europe/Brussels", ["belgium"]),
    "NL": ("west", 17.9, "Europe/Amsterdam", ["netherlands"]),
    "LU": ("west", 0.7, "Europe/Luxembourg", ["luxembourg"]),
    "DE": ("central", 84.0, "Europe/Berlin", ["germany"]),
    "AT": ("central", 9.1, "Europe/Vienna", ["austria"]),
    "CH": ("central", 8.8, "Europe/Zurich", ["switzerland"]),
    "PL": ("central", 37.0, "Europe/Warsaw", ["poland"]),
    "CZ": ("central", 10.9, "Europe/Prague", ["czech republic", "czechia"]),
    "SK": ("central", 5.4, "Europe/Bratislava", ["slovakia"]),
    "HU": ("central", 9.6, "Europe/Budapest", ["hungary"]),
    "GB": ("north", 68.0, "Europe/London",
           ["england", "scotland", "wales", "northern ireland", "united kingdom"]),
    "IE": ("north", 5.3, "Europe/Dublin", ["ireland", "republic of ireland"]),
    "SE": ("north", 10.5, "Europe/Stockholm", ["sweden"]),
    "NO": ("north", 5.5, "Europe/Oslo", ["norway"]),
    "DK": ("north", 5.9, "Europe/Copenhagen", ["denmark"]),
    "FI": ("north", 5.6, "Europe/Helsinki", ["finland"]),
    "IS": ("north", 0.4, "Atlantic/Reykjavik", ["iceland"]),
    "EE": ("north", 1.4, "Europe/Tallinn", ["estonia"]),
    "LV": ("north", 1.9, "Europe/Riga", ["latvia"]),
    "LT": ("north", 2.8, "Europe/Vilnius", ["lithuania"]),
    "IT": ("south_east", 59.0, "Europe/Rome", ["italy"]),
    "GR": ("south_east", 10.4, "Europe/Athens", ["greece"]),
    "RO": ("south_east", 19.0, "Europe/Bucharest", ["romania"]),
    "BG": ("south_east", 6.5, "Europe/Sofia", ["bulgaria"]),
    "TR": ("south_east", 85.0, "Europe/Istanbul", ["turkey", "türkiye"]),
    "CY": ("south_east", 1.3, "Asia/Nicosia", ["cyprus"]),
    "MT": ("south_east", 0.5, "Europe/Malta", ["malta"]),
    "UA": ("south_east", 38.0, "Europe/Kyiv", ["ukraine"]),
    "MD": ("south_east", 2.6, "Europe/Chisinau", ["moldova"]),
    "RS": ("balkans", 6.7, "Europe/Belgrade", ["serbia"]),
    "HR": ("balkans", 3.9, "Europe/Zagreb", ["croatia"]),
    "BA": ("balkans", 3.2, "Europe/Sarajevo", ["bosnia-herzegovina", "bosnia and herzegovina"]),
    "ME": ("balkans", 0.6, "Europe/Podgorica", ["montenegro"]),
    "MK": ("balkans", 1.8, "Europe/Skopje", ["north macedonia", "macedonia"]),
    "AL": ("balkans", 2.8, "Europe/Tirane", ["albania"]),
    "SI": ("balkans", 2.1, "Europe/Ljubljana", ["slovenia"]),
    "XK": ("balkans", 1.8, "Europe/Belgrade", ["kosovo"]),
}
NAME_TO_ISO = {n: iso for iso, (_, _, _, names) in COUNTRIES.items() for n in names}

ZONE_DEPLOYMENT = {
    "west": "eu-west",
    "central": "eu-central",
    "north": "eu-north",
    "south_east": "eu-south",
    "balkans": "eu-south",
}

DEPLOYMENTS = {
    "eu-west":    {"aws_region": "eu-west-3",    "function": "api", "alias": "live", "min_pc": 0, "max_pc": 200},
    "eu-central": {"aws_region": "eu-central-1", "function": "api", "alias": "live", "min_pc": 0, "max_pc": 200},
    "eu-north":   {"aws_region": "eu-north-1",   "function": "api", "alias": "live", "min_pc": 0, "max_pc": 200},
    "eu-south":   {"aws_region": "eu-south-1",   "function": "api", "alias": "live", "min_pc": 0, "max_pc": 200},
}


def _calculate_weights():
    by_dep = defaultdict(dict)
    for iso, (zone, weight, _, _) in COUNTRIES.items():
        by_dep[ZONE_DEPLOYMENT[zone]][iso] = weight
    return {d: {iso: w / sum(ws.values()) for iso, w in ws.items()} for d, ws in by_dep.items()}


WEIGHTS = _calculate_weights()

COMPETITIONS = {
    "PL": (0.35, "league"), "PD": (0.35, "league"), "BL1": (0.35, "league"), "SA": (0.35, "league"),
    "FL1": (0.35, "league"), "PPL": (0.35, "league"), "DED": (0.30, "league"),
    "CL": (0.80, "teams"), "EC": (2.00, "teams"), "WC": (2.00, "teams"),
}
STAGE_MULT = {"FINAL": 2.0, "SEMI_FINALS": 1.6, "QUARTER_FINALS": 1.3, "LAST_16": 1.15}
KNOCKOUT_STAGES = {"FINAL", "SEMI_FINALS", "QUARTER_FINALS", "LAST_16", "LAST_32",
                   "PLAYOFFS", "THIRD_PLACE"}
TOP_TEAMS = ("real madrid", "fc barcelona", "atlético", "benfica", "sporting clube de portugal",
             "fc porto", "manchester united", "manchester city", "liverpool", "arsenal",
             "chelsea", "tottenham", "bayern", "dortmund", "paris saint-germain", "juventus",
             "internazionale", "milan", "napoli", "ajax")

PHQ_CATEGORIES = "sports,concerts,festivals,performing-arts,conferences,expos"
PHQ_MIN_RANK = 60
PHQ_EFFECT_PER_100K = 0.5

TM_LARGE_VENUES = ("stadium", "stadion", "stade", "estadio", "estádio", "stadio",
                   "olympia", "wembley", "arena")
TM_LARGE_VENUE_EFFECT = 0.5
TM_RELEVANT_COUNTRIES = ["GB", "DE", "FR", "ES", "NL", "BE", "IE", "SE", "NO", "DK", "AT", "CH", "PL", "IT", "PT"]


def slot_key(weekday, hour):
    return f"{weekday}-{hour}"


def _cache(name, ttl_s, producer):
    f = CACHE_DIR / f"prewarm_{name}.json"
    try:
        if time.time() - f.stat().st_mtime < ttl_s:
            return json.loads(f.read_text())
    except (OSError, ValueError):
        pass
    data = producer()
    try:
        f.write_text(json.dumps(data))
    except OSError as e:
        log.warning("Cache %s could not be written: %s", name, e)
    return data


def _parse_utc(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


@dataclass
class Event:
    country: str
    start: dt.datetime
    end: dt.datetime
    effect: float
    description: str
    source: str = ""


# ----------------------------------------------------------------------------
# Historical Traffic Profile (CloudWatch + Realistic Baseline Simulation)
# ----------------------------------------------------------------------------
def _simulated_baseline_profile():
    """Generates a realistic 24-hour diurnal profile for local testing and demos."""
    hourly_curve = [
        6.0, 4.0, 3.0, 2.5, 3.0, 5.0, 8.0, 12.0, 16.0, 19.0, 21.0, 22.0,
        25.0, 24.0, 20.0, 19.0, 21.0, 23.0, 27.0, 32.0, 35.0, 30.0, 22.0, 12.0
    ]
    profile = {}
    for weekday in range(7):
        day_factor = 0.85 if weekday >= 5 else 1.0
        for hour in range(24):
            profile[slot_key(weekday, hour)] = round(hourly_curve[hour] * day_factor, 1)
    return profile


def get_historical_profile(dep, days=28):
    if boto3 is None:
        return _simulated_baseline_profile()

    try:
        cw = boto3.client("cloudwatch", region_name=dep["aws_region"])
        end = dt.datetime.now(dt.timezone.utc).replace(minute=0, second=0, microsecond=0)
        start = end - dt.timedelta(days=days)
        dim = [{"Name": "FunctionName", "Value": dep["function"]}]

        def q(i, metric, stat):
            return {"Id": i, "ReturnData": True, "MetricStat": {
                "Metric": {"Namespace": "AWS/Lambda", "MetricName": metric, "Dimensions": dim},
                "Period": 300, "Stat": stat}}

        series = defaultdict(dict)
        for page in cw.get_paginator("get_metric_data").paginate(
                MetricDataQueries=[q("inv", "Invocations", "Sum"), q("dur", "Duration", "Average")],
                StartTime=start, EndTime=end, ScanBy="TimestampAscending"):
            for r in page["MetricDataResults"]:
                for ts, v in zip(r["Timestamps"], r["Values"]):
                    series[r["Id"]][ts] = v

        hourly_peak = defaultdict(float)
        for ts, n in series["inv"].items():
            duration_sec = series["dur"].get(ts, 100.0) / 1000.0
            k = (ts.date(), ts.hour)
            hourly_peak[k] = max(hourly_peak[k], n / 300.0 * duration_sec)

        by_slot = defaultdict(list)
        cur = start
        while cur < end:
            by_slot[(cur.weekday(), cur.hour)].append(hourly_peak.get((cur.date(), cur.hour), 0.0))
            cur += dt.timedelta(hours=1)

        result = {slot_key(*k): statistics.median(v) for k, v in by_slot.items()}
        if not any(result.values()):
            return _simulated_baseline_profile()
        return result
    except Exception as e:
        log.warning("[%s] CloudWatch metrics unavailable (%s): using baseline profile",
                    dep.get("aws_region"), e)
        return _simulated_baseline_profile()


# ----------------------------------------------------------------------------
# Source: Football (football-data.org)
# ----------------------------------------------------------------------------
FOOTBALL_API = "https://api.football-data.org/v4"


def _fb_get(path, **params):
    r = requests.get(f"{FOOTBALL_API}{path}",
                     headers={"X-Auth-Token": os.environ.get("FOOTBALL_API_KEY", "")},
                     params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def _get_team_countries():
    def fetch():
        out = {}
        for code, (_, source_type) in COMPETITIONS.items():
            if source_type != "teams":
                continue
            try:
                for t in _fb_get(f"/competitions/{code}/teams")["teams"]:
                    out[str(t["id"])] = (t.get("area") or {}).get("name", "")
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code in (403, 404):
                    log.warning("Competition %s unavailable (%s)", code, e.response.status_code)
                else:
                    raise
        return out
    return _cache("team_countries", 7 * 86400, fetch)


def _get_raw_matches(now):
    def fetch():
        today = now.date()
        return _fb_get("/matches", competitions=",".join(COMPETITIONS),
                       dateFrom=(today - dt.timedelta(days=1)).isoformat(),
                       dateTo=(today + dt.timedelta(days=3)).isoformat())["matches"]
    return _cache("matches", 3 * 3600, fetch)


def collect_football_events(now):
    if not os.environ.get("FOOTBALL_API_KEY"):
        log.info("Football: FOOTBALL_API_KEY not set, source disabled")
        return []
    team_countries = _get_team_countries()
    out = []
    try:
        matches = _get_raw_matches(now)
    except Exception as e:
        log.warning("Football: Error fetching matches (%s)", e)
        return []

    for m in matches:
        if m.get("status") not in ("SCHEDULED", "TIMED", "IN_PLAY", "PAUSED"):
            continue
        code = (m.get("competition") or {}).get("code")
        if code not in COMPETITIONS:
            continue
        base_effect, source_type = COMPETITIONS[code]
        stage = m.get("stage")
        teams = [m.get("homeTeam") or {}, m.get("awayTeam") or {}]
        names = [(t.get("name") or "").lower() for t in teams]
        top_tier = [any(g in n for g in TOP_TEAMS) for n in names]
        extra = 1.3 if all(top_tier) else 1.0

        by_country = {}
        for t, is_top in zip(teams, top_tier):
            country_name = (m.get("area") or {}).get("name", "") if source_type == "league" \
                else team_countries.get(str(t.get("id")), "")
            iso = NAME_TO_ISO.get(country_name.strip().lower())
            if not iso:
                continue
            ef = base_effect * STAGE_MULT.get(stage, 1.0) * extra * (1.5 if is_top else 1.0)
            by_country[iso] = max(by_country.get(iso, 0.0), ef)

        start = _parse_utc(m["utcDate"])
        duration = KNOCKOUT_MATCH_DURATION if stage in KNOCKOUT_STAGES else REGULAR_MATCH_DURATION
        desc = f"{teams[0].get('name')} vs {teams[1].get('name')} [{code}{'/' + stage if stage else ''}]"
        for iso, ef in by_country.items():
            if ef >= MIN_EFFECT:
                out.append(Event(iso, start - PRE_EVENT_WINDOW, start + duration,
                                 min(ef, MAX_EFFECT), desc, "football"))
    return out


# ----------------------------------------------------------------------------
# Source: PredictHQ
# ----------------------------------------------------------------------------
def collect_predicthq_events(now):
    token = os.environ.get("PREDICTHQ_TOKEN")
    if not token:
        log.info("PredictHQ: PREDICTHQ_TOKEN not set, source disabled")
        return []

    def fetch():
        url = "https://api.predicthq.com/v1/events/"
        today = now.date()
        params = {"category": PHQ_CATEGORIES,
                  "country": ",".join(p for p in COUNTRIES if p != "XK"),
                  "active.gte": (today - dt.timedelta(days=1)).isoformat(),
                  "active.lte": (today + dt.timedelta(days=3)).isoformat(),
                  "rank.gte": PHQ_MIN_RANK, "sort": "start", "limit": 200}
        out = []
        while url and len(out) < 2000:
            r = requests.get(url, headers={"Authorization": f"Bearer {token}"},
                             params=params, timeout=20)
            r.raise_for_status()
            j = r.json()
            out += j.get("results", [])
            url, params = j.get("next"), None
        return out

    out = []
    for ev in _cache("predicthq", 6 * 3600, fetch):
        iso = (ev.get("country") or "").upper()
        if iso not in COUNTRIES or not ev.get("start"):
            continue
        ef = PHQ_EFFECT_PER_100K * (ev.get("phq_attendance") or 0) / 100_000
        if ef < MIN_EFFECT:
            continue
        start = _parse_utc(ev["start"])
        end = _parse_utc(ev["end"]) if ev.get("end") else start + REGULAR_MATCH_DURATION
        out.append(Event(iso, start - PRE_EVENT_WINDOW, end + PRE_EVENT_WINDOW, min(ef, MAX_EFFECT),
                         f"{ev.get('title')} [{ev.get('category')}, ~{ev.get('phq_attendance')} pax]",
                         "predicthq"))
    return out


# ----------------------------------------------------------------------------
# Source: Ticketmaster
# ----------------------------------------------------------------------------
def collect_ticketmaster_events(now):
    key = os.environ.get("TICKETMASTER_API_KEY")
    if not key:
        log.info("Ticketmaster: TICKETMASTER_API_KEY not set, source disabled")
        return []

    def fetch():
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        out = []
        countries_to_query = [p for p in TM_RELEVANT_COUNTRIES if p in COUNTRIES]
        for iso in countries_to_query:
            try:
                r = requests.get("https://app.ticketmaster.com/discovery/v2/events.json", params={
                    "apikey": key, "countryCode": iso, "classificationName": "music",
                    "startDateTime": (now - dt.timedelta(hours=12)).strftime(fmt),
                    "endDateTime": (now + dt.timedelta(days=3)).strftime(fmt),
                    "size": 100, "sort": "date,asc"}, timeout=15)
                r.raise_for_status()
            except requests.RequestException as e:
                log.warning("Ticketmaster %s: %s", iso, e)
                continue
            out += [dict(ev, _country=iso) for ev in (r.json().get("_embedded") or {}).get("events", [])]
            time.sleep(0.2)
        return out

    out = []
    for ev in _cache("ticketmaster", 6 * 3600, fetch):
        start_str = ((ev.get("dates") or {}).get("start") or {}).get("dateTime")
        venues = (ev.get("_embedded") or {}).get("venues") or [{}]
        venue_name = (venues[0].get("name") or "").lower()
        if not start_str or not any(w in venue_name for w in TM_LARGE_VENUES):
            continue
        start = _parse_utc(start_str)
        out.append(Event(ev["_country"], start - dt.timedelta(hours=1), start + dt.timedelta(hours=4),
                         TM_LARGE_VENUE_EFFECT, f"{ev.get('name')} @ {venues[0].get('name')}",
                         "ticketmaster"))
    return out


# ----------------------------------------------------------------------------
# Source: Manual Events (supports both English and Portuguese schema keys)
# ----------------------------------------------------------------------------
def collect_manual_events(now):
    env_path = os.environ.get("MANUAL_EVENTS") or os.environ.get("EVENTOS_MANUAIS")
    if env_path:
        f = Path(env_path)
    else:
        base = Path(__file__).resolve().parent
        f = base / "ManualEvents.json"
        if not f.exists():
            f = base / "manual_events.json"
        if not f.exists():
            f = base / "EventosManuais.json"

    if not f.exists():
        log.warning("Manual Events: File %s not found", f)
        return []

    try:
        content = json.loads(f.read_text(encoding="utf-8"))
    except Exception as err:
        log.warning("Manual Events: Error reading %s: %s", f, err)
        return []

    out = []
    for e in content:
        try:
            countries_list = e.get("countries") or e.get("paises")
            zone = e.get("zone") or e.get("zona")
            desc = e.get("description") or e.get("descricao", "manual")
            start = _parse_utc(e.get("start") or e.get("inicio"))
            end = _parse_utc(e.get("end") or e.get("fim"))
            effect = float(e.get("effect") or e.get("efeito", 1.0))

            if countries_list:
                isos = [p.upper() for p in countries_list]
            elif zone:
                zone_std = "west" if zone in ("west", "oeste") else \
                           "central" if zone == "central" else \
                           "north" if zone in ("north", "norte") else \
                           "south_east" if zone in ("south_east", "sul_este", "sul") else zone
                isos = [i for i, v in COUNTRIES.items() if v[0] == zone_std]
            else:
                isos = list(COUNTRIES)

            for iso in isos:
                if iso in COUNTRIES:
                    out.append(Event(iso, start, end, effect, desc, "manual"))
        except (KeyError, ValueError, TypeError) as err:
            log.warning("Manual event invalid %r: %s", e, err)
    return out


SOURCES = {
    "football": collect_football_events,
    "predicthq": collect_predicthq_events,
    "ticketmaster": collect_ticketmaster_events,
    "manual": collect_manual_events,
}


def collect_all_events(now):
    all_events = []
    for name, fn in SOURCES.items():
        try:
            evs = fn(now)
        except Exception as e:
            log.error("Source %s failed (%s): skipped in this run", name, e)
            continue
        for e in evs:
            e.effect *= SOURCE_WEIGHTS.get(name, 1.0)
        log.info("Source %s: %d events collected", name, len(evs))
        all_events += evs
    return all_events


# ----------------------------------------------------------------------------
# National Holidays
# ----------------------------------------------------------------------------
@lru_cache(maxsize=None)
def _get_holidays(iso, year):
    if holidays is None:
        return {}
    try:
        return holidays.country_holidays(iso, years=year)
    except (NotImplementedError, KeyError):
        return {}


@lru_cache(maxsize=None)
def _get_timezone(name):
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return dt.timezone.utc


def holiday_traffic_fraction(dep_name, when):
    h = 0.0
    for iso, weight in WEIGHTS[dep_name].items():
        local_date = when.astimezone(_get_timezone(COUNTRIES[iso][2])).date()
        if local_date in _get_holidays(iso, local_date.year):
            h += weight
    return h


def expected_baseline(dep_name, profile, when):
    normal = profile.get(slot_key(when.weekday(), when.hour), 0.0)
    if when.weekday() >= 5:
        return normal
    h = holiday_traffic_fraction(dep_name, when)
    if h == 0:
        return normal
    holiday = profile.get(slot_key(HOLIDAY_PROFILE_DAY, when.hour), normal)
    return (1 - h) * normal + h * holiday


# ----------------------------------------------------------------------------
# Target Provisioned Concurrency Calculation
# ----------------------------------------------------------------------------
def calculate_traffic_multiplier(dep_name, events, when):
    mult = 1.0
    for iso, weight in WEIGHTS[dep_name].items():
        active = [e.effect for e in events if e.country == iso and e.start <= when <= e.end]
        if active:
            mult += weight * max(active, key=abs)
    return max(MIN_MULT, min(MAX_BOOST, mult))


def compute_target_concurrency(dep_name, dep, profile, events, now):
    best = 0.0
    for minutes in range(0, LEAD_MIN + 1, 10):
        t = now + dt.timedelta(minutes=minutes)
        best = max(best, expected_baseline(dep_name, profile, t) * calculate_traffic_multiplier(dep_name, events, t))
    pc = math.ceil(best * HEADROOM)
    return max(dep["min_pc"], min(dep["max_pc"], pc))


# ----------------------------------------------------------------------------
# AWS Lambda Provisioning Execution (or Safe Local Simulation)
# ----------------------------------------------------------------------------
RESOURCE_NOT_FOUND = {"ProvisionedConcurrencyConfigNotFoundException", "ResourceNotFoundException"}


def get_current_concurrency(lam, dep):
    if lam is None:
        return 5  # Realistic simulated concurrency baseline
    try:
        r = lam.get_provisioned_concurrency_config(FunctionName=dep["function"],
                                                   Qualifier=dep["alias"])
        return r.get("RequestedProvisionedConcurrentExecutions", 0)
    except ClientError as e:
        if e.response["Error"]["Code"] in RESOURCE_NOT_FOUND:
            return 0
        log.warning("[%s] Error retrieving current PC (%s): assuming 0", dep.get("aws_region"), e)
        return 0
    except Exception:
        return 5


def is_adjustment_worthwhile(current, target):
    if current == target:
        return False
    if current == 0 or target == 0:
        return True
    return abs(target - current) / current >= HYSTERESIS


def apply_concurrency_update(name, dep, new_target):
    lam = boto3.client("lambda", region_name=dep["aws_region"]) if boto3 is not None else None
    current = get_current_concurrency(lam, dep)
    if not is_adjustment_worthwhile(current, new_target):
        log.info("[%s] Retaining concurrency %s (target %s)", name, current, new_target)
        return current
    sim_label = "  (DRY_RUN / SIMULATION)" if (DRY_RUN or lam is None) else ""
    log.info("[%s] Provisioned concurrency %s -> %s%s", name, current, new_target, sim_label)
    if DRY_RUN or lam is None:
        return current
    if new_target == 0:
        try:
            lam.delete_provisioned_concurrency_config(FunctionName=dep["function"],
                                                      Qualifier=dep["alias"])
        except ClientError as e:
            if e.response["Error"]["Code"] not in RESOURCE_NOT_FOUND:
                raise
    else:
        lam.put_provisioned_concurrency_config(FunctionName=dep["function"],
                                               Qualifier=dep["alias"],
                                               ProvisionedConcurrentExecutions=new_target)
    return new_target


# ----------------------------------------------------------------------------
# Main Process Pipeline
# ----------------------------------------------------------------------------
def main():
    now = dt.datetime.now(dt.timezone.utc)

    if holidays is None:
        log.info("Package 'holidays' not installed: skipping national holidays (install via: pip install holidays)")
    if boto3 is None:
        log.info("Package 'boto3' not installed: running in local simulation mode / exporting to cache manager")

    # 1. Collect events from all active sources
    events = collect_all_events(now)

    # 2. Analyze events and extract cache directives using Google Gemini AI
    analyzed_events = analyze_events_with_gemini(events)

    # 3. Fine-tune event effects based on AI adjustments
    for e, ai_data in zip(events, analyzed_events):
        if "adjusted_effect" in ai_data:
            try:
                e.effect = max(MIN_MULT, min(MAX_EFFECT, float(ai_data["adjusted_effect"])))
            except (ValueError, TypeError):
                pass

    # Log events active now or starting in the next 24 hours
    for e in sorted(events, key=lambda x: x.start):
        if e.end >= now and e.start <= now + dt.timedelta(hours=24):
            log.info("Event [%s] %+.2f %s -> %s | %s (%s)", e.country, e.effect,
                     e.start.strftime("%d/%m %H:%M"), e.end.strftime("%H:%M UTC"),
                     e.description, e.source)

    deployments_result = {}
    for name, dep in DEPLOYMENTS.items():
        try:
            profile = _cache(f"profile_{name}", 86400, lambda d=dep: get_historical_profile(d))
            holiday_fraction = holiday_traffic_fraction(name, now)
            if holiday_fraction:
                log.info("[%s] %.0f%% of traffic is in a national holiday today", name, holiday_fraction * 100)

            target = compute_target_concurrency(name, dep, profile, events, now)
            multiplier = calculate_traffic_multiplier(name, events, now)
            baseline = expected_baseline(name, profile, now)

            lam = boto3.client("lambda", region_name=dep["aws_region"]) if boto3 is not None else None
            current = get_current_concurrency(lam, dep)
            apply_concurrency_update(name, dep, target)

            covered_countries = [iso for iso, (z, _, _, _) in COUNTRIES.items() if ZONE_DEPLOYMENT.get(z) == name]
            deployments_result[name] = {
                "aws_region": dep["aws_region"],
                "function": dep["function"],
                "multiplier": round(multiplier, 2),
                "baseline_expected": round(baseline, 2),
                "target_pc": target,
                "current_pc": current,
                "covered_countries": covered_countries,
            }
        except Exception as e:
            log.error("[%s] Processing failed (%s): retaining current state", name, e)

    # 4. Export consolidated directives for downstream Cache Manager
    cache_output_path = Path(os.environ.get(
        "CACHE_MANAGER_OUTPUT",
        Path(__file__).resolve().parent / "cache_manager_feed.json"
    ))
    export_to_cache_manager(
        output_path=cache_output_path,
        now=now,
        deployments_result=deployments_result,
        analyzed_events=analyzed_events,
        dry_run=DRY_RUN or (boto3 is None),
    )


def lambda_handler(event=None, context=None):
    main()
    return {"dry_run": DRY_RUN}


if __name__ == "__main__":
    main()
