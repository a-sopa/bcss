"""Decoy Cryptographic Material and Canary Key Generator."""

from dataclasses import dataclass
from typing import Dict, Tuple

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


@dataclass
class CanaryCryptoBundle:
    """Bundle of honey-cryptographic assets planted for attacker deception."""
    rsa_private_key_pem: str
    rsa_public_key_pem: str
    fake_kms_arn: str
    fake_jwt_secret: str
    canary_id: str


class CanaryCryptoGenerator:
    """Generates traceable cryptographic decoys for honeypot honeypath detection."""

    def __init__(self):
        self._registered_tokens = {}

    def generate_bundle(self, canary_id: str = "picoas_cloud_canary_01") -> CanaryCryptoBundle:
        """Generate a fresh RSA keypair and cloud canary tokens."""
        # Generate 2048-bit RSA key for honeypot decoy
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )

        priv_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("utf-8")

        pub_pem = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")

        fake_kms = f"arn:aws:kms:eu-west-1:123456789012:key/canary-{canary_id}"
        fake_jwt = f"honey_jwt_secret_{canary_id}_99x"

        bundle = CanaryCryptoBundle(
            rsa_private_key_pem=priv_pem,
            rsa_public_key_pem=pub_pem,
            fake_kms_arn=fake_kms,
            fake_jwt_secret=fake_jwt,
            canary_id=canary_id,
        )

        self._registered_tokens[canary_id] = bundle
        return bundle

    def is_canary(self, token_str: str) -> bool:
        """Check if a string matches any active canary token."""
        for cid, bundle in self._registered_tokens.items():
            if cid in token_str or bundle.fake_kms_arn in token_str or bundle.fake_jwt_secret in token_str:
                return True
        return False


CANARY_GENERATOR = CanaryCryptoGenerator()
