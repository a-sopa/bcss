"""Unit tests for GeoIP resolution and offline fallback."""

import unittest

from cloud_honeypot_ai.core.geoip import DEFAULT_RESOLVER, GeoIPResolver, GeoLocation


class TestGeoIP(unittest.TestCase):

    def setUp(self):
        self.resolver = GeoIPResolver(use_online_api=False)

    def test_localhost_and_private_ip(self):
        geo = self.resolver.resolve("127.0.0.1")
        self.assertTrue(geo.is_private)
        self.assertEqual(geo.country_code, "LAN")
        self.assertEqual(geo.country, "Local / Internal Network")

        geo_vpc = self.resolver.resolve("10.0.1.42")
        self.assertTrue(geo_vpc.is_private)

    def test_known_botnet_subnets(self):
        # 185.220.101.5 is in Tor / Germany subnet 185.220.100.0/22
        geo = self.resolver.resolve("185.220.101.5")
        self.assertEqual(geo.country, "Germany")
        self.assertEqual(geo.country_code, "DE")
        self.assertEqual(geo.city, "Frankfurt")

        # 45.154.255.88 is in Russia subnet 45.154.255.0/24
        geo_ru = self.resolver.resolve("45.154.255.88")
        self.assertEqual(geo_ru.country, "Russia")
        self.assertEqual(geo_ru.country_code, "RU")

    def test_synthetic_deterministic_resolution(self):
        # Any arbitrary public IP should resolve deterministically
        ip = "151.101.1.69"
        geo1 = self.resolver.resolve(ip)
        geo2 = self.resolver.resolve(ip)

        self.assertEqual(geo1.country, geo2.country)
        self.assertEqual(geo1.city, geo2.city)
        self.assertEqual(geo1.latitude, geo2.latitude)
        self.assertFalse(geo1.is_private)

    def test_to_dict_serialization(self):
        geo = self.resolver.resolve("185.220.101.5")
        d = geo.to_dict()
        self.assertIn("country", d)
        self.assertIn("country_code", d)
        self.assertIn("asn", d)
        self.assertIn("latitude", d)


if __name__ == "__main__":
    unittest.main()
