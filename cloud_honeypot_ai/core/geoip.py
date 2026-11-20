"""GeoIP resolution and IP intelligence tracker with offline fallback."""

from dataclasses import dataclass
import hashlib
import ipaddress
import json
import logging
from typing import Any, Dict, Optional
import urllib.request

from cloud_honeypot_ai.config import CONFIG

logger = logging.getLogger("honeypot.geoip")


@dataclass
class GeoLocation:
    """Geographic and ASN information for an IP address."""
    ip: str
    country: str
    country_code: str
    city: str
    region: str
    latitude: float
    longitude: float
    asn: str
    isp: str
    is_private: bool = False
    # Where the data came from: "online" (ip-api.com), "private" (LAN/loopback),
    # "synthetic" (offline demo table or hash-seeded placeholder: NOT a real location), "invalid".
    source: str = "synthetic"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ip": self.ip,
            "country": self.country,
            "country_code": self.country_code,
            "city": self.city,
            "region": self.region,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "asn": self.asn,
            "isp": self.isp,
            "is_private": self.is_private,
            "source": self.source,
        }


# Rich offline database for common scanning subnets, botnet origins, and demo addresses
KNOWN_GEO_RANGES = [
    {
        "cidr": "185.220.100.0/22",
        "country": "Germany",
        "country_code": "DE",
        "city": "Frankfurt",
        "region": "Hesse",
        "lat": 50.1109,
        "lon": 8.6821,
        "asn": "AS208323",
        "isp": "Tor Exit Node Network",
    },
    {
        "cidr": "45.154.255.0/24",
        "country": "Russia",
        "country_code": "RU",
        "city": "Moscow",
        "region": "Moscow",
        "lat": 55.7558,
        "lon": 37.6173,
        "asn": "AS49447",
        "isp": "DataCamp Cyber Hosting",
    },
    {
        "cidr": "103.203.57.0/24",
        "country": "China",
        "country_code": "CN",
        "city": "Shenzhen",
        "region": "Guangdong",
        "lat": 22.5431,
        "lon": 114.0579,
        "asn": "AS4134",
        "isp": "Chinanet Backbone Scanner",
    },
    {
        "cidr": "194.26.29.0/24",
        "country": "Netherlands",
        "country_code": "NL",
        "city": "Amsterdam",
        "region": "North Holland",
        "lat": 52.3676,
        "lon": 4.9041,
        "asn": "AS44592",
        "isp": "Serverion Bulletproof B.V.",
    },
    {
        "cidr": "198.235.24.0/24",
        "country": "United States",
        "country_code": "US",
        "city": "Ashburn",
        "region": "Virginia",
        "lat": 39.0438,
        "lon": -77.4874,
        "asn": "AS398324",
        "isp": "Shadowserver Botnet Monitor",
    },
    {
        "cidr": "177.54.144.0/20",
        "country": "Brazil",
        "country_code": "BR",
        "city": "São Paulo",
        "region": "São Paulo",
        "lat": -23.5505,
        "lon": -46.6333,
        "asn": "AS28573",
        "isp": "Claro Brasil Broadband",
    },
    {
        "cidr": "193.136.0.0/16",
        "country": "Portugal",
        "country_code": "PT",
        "city": "Lisbon",
        "region": "Lisboa",
        "lat": 38.7223,
        "lon": -9.1393,
        "asn": "AS1930",
        "isp": "FCT - RCTS Lisboa",
    },
    {
        "cidr": "185.196.220.0/24",
        "country": "France",
        "country_code": "FR",
        "city": "Paris",
        "region": "Île-de-France",
        "lat": 48.8566,
        "lon": 2.3522,
        "asn": "AS16276",
        "isp": "OVH SAS Hosting",
    },
    {
        "cidr": "118.193.32.0/20",
        "country": "Hong Kong",
        "country_code": "HK",
        "city": "Hong Kong",
        "region": "Kowloon",
        "lat": 22.3193,
        "lon": 114.1694,
        "asn": "AS55933",
        "isp": "Cloudie Web Services",
    },
]

# Country pool for pseudo-random deterministic synthesis of unknown external IPs
SYNTHETIC_COUNTRIES = [
    ("United States", "US", "New York", "NY", 40.7128, -74.0060, "AS15169 Google Cloud"),
    ("China", "CN", "Shanghai", "Shanghai", 31.2304, 121.4737, "AS4808 China Unicom"),
    ("Russia", "RU", "Saint Petersburg", "SPB", 59.9343, 30.3351, "AS12389 Rostelecom"),
    ("Brazil", "BR", "Rio de Janeiro", "RJ", -22.9068, -43.1729, "AS26615 TIM Brasil"),
    ("Germany", "DE", "Berlin", "Berlin", 52.5200, 13.4050, "AS3320 Deutsche Telekom"),
    ("United Kingdom", "GB", "London", "London", 51.5074, -0.1278, "AS2856 British Telecom"),
    ("India", "IN", "Mumbai", "Maharashtra", 19.0760, 72.8777, "AS55836 Reliance Jio"),
    ("Vietnam", "VN", "Hanoi", "Hanoi", 21.0285, 105.8542, "AS7552 Viettel"),
    ("Netherlands", "NL", "Rotterdam", "South Holland", 51.9244, 4.4777, "AS1136 KPN"),
    ("Portugal", "PT", "Porto", "Porto", 41.1579, -8.6291, "AS2860 MEO Portugal"),
]


class GeoIPResolver:
    """Resolves IP addresses with offline database and fast fallback."""

    MAX_CACHE = 20000

    def __init__(self, use_online_api: bool = False):
        self.use_online_api = use_online_api
        self.cache: Dict[str, GeoLocation] = {}
        self._parsed_ranges = []
        for entry in KNOWN_GEO_RANGES:
            try:
                network = ipaddress.ip_network(entry["cidr"])
                self._parsed_ranges.append((network, entry))
            except Exception:
                pass

    def resolve(self, ip_str: str) -> GeoLocation:
        """Resolve IP address to GeoLocation with multi-tier fallback."""
        cached = self.cache.get(ip_str)
        if cached is not None:
            return cached
        if len(self.cache) >= self.MAX_CACHE:
            self.cache.clear()

        # Check for private / loopback IP
        try:
            ip_obj = ipaddress.ip_address(ip_str)
            if ip_obj.is_private or ip_obj.is_loopback:
                geo = GeoLocation(
                    ip=ip_str,
                    country="Local / Internal Network",
                    country_code="LAN",
                    city="Cloud VPC Internal",
                    region="Private Subnet",
                    latitude=38.7223,
                    longitude=-9.1393,
                    asn="AS-PRIVATE",
                    isp="Internal Cloud VPC / Localhost",
                    is_private=True,
                    source="private",
                )
                self.cache[ip_str] = geo
                return geo
        except ValueError:
            # Not a valid IP string, return fallback
            return GeoLocation(
                ip=ip_str,
                country="Unknown",
                country_code="XX",
                city="Unknown",
                region="Unknown",
                latitude=0.0,
                longitude=0.0,
                asn="AS-UNKNOWN",
                isp="Unknown ISP",
                source="invalid",
            )

        # 1. Real lookup first when explicitly enabled (GEOIP_ONLINE=true)
        if self.use_online_api:
            online_geo = self._query_online_api(ip_str)
            if online_geo:
                self.cache[ip_str] = online_geo
                return online_geo

        # 2. Offline demo table of common scanner/botnet CIDR subnets (synthetic)
        for network, data in self._parsed_ranges:
            if ip_obj in network:
                geo = GeoLocation(
                    ip=ip_str,
                    country=data["country"],
                    country_code=data["country_code"],
                    city=data["city"],
                    region=data["region"],
                    latitude=data["lat"],
                    longitude=data["lon"],
                    asn=data["asn"],
                    isp=data["isp"],
                    is_private=False,
                )
                self.cache[ip_str] = geo
                return geo

        # 3. Deterministic synthetic mapping for public IPs (hash-seeded)
        # Guarantees that any arbitrary IP gets a consistent, realistic country/city
        ip_hash = int(hashlib.md5(ip_str.encode("utf-8")).hexdigest(), 16)
        entry = SYNTHETIC_COUNTRIES[ip_hash % len(SYNTHETIC_COUNTRIES)]
        jitter_lat = ((ip_hash % 200) - 100) / 1000.0
        jitter_lon = (((ip_hash >> 8) % 200) - 100) / 1000.0

        geo = GeoLocation(
            ip=ip_str,
            country=entry[0],
            country_code=entry[1],
            city=entry[2],
            region=entry[3],
            latitude=entry[4] + jitter_lat,
            longitude=entry[5] + jitter_lon,
            asn=f"AS{20000 + (ip_hash % 40000)}",
            isp=entry[6],
            is_private=False,
        )
        self.cache[ip_str] = geo
        return geo

    def _query_online_api(self, ip_str: str) -> Optional[GeoLocation]:
        """Optional online GeoIP query (e.g. ip-api.com). Fails safely to fallback."""
        try:
            url = f"http://ip-api.com/json/{ip_str}?fields=status,country,countryCode,regionName,city,lat,lon,as,isp"
            req = urllib.request.Request(url, headers={"User-Agent": "Honeypot-GeoIP/1.0"})
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("status") == "success":
                    return GeoLocation(
                        ip=ip_str,
                        country=data.get("country", "Unknown"),
                        country_code=data.get("countryCode", "XX"),
                        city=data.get("city", "Unknown"),
                        region=data.get("regionName", "Unknown"),
                        latitude=float(data.get("lat", 0.0)),
                        longitude=float(data.get("lon", 0.0)),
                        asn=data.get("as", "Unknown ASN"),
                        isp=data.get("isp", "Unknown ISP"),
                        is_private=False,
                        source="online",
                    )
        except Exception as e:
            logger.debug("Online GeoIP query failed for %s: %s", ip_str, e)
        return None


# Global resolver singleton
DEFAULT_RESOLVER = GeoIPResolver(use_online_api=CONFIG.geoip_online)
