import json
from base64 import b64encode

from django.test import override_settings

from tests.utils import ClientWithCsrfChecks

HAS_CRYPTOGRAPHY = True
try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
except ImportError:
    HAS_CRYPTOGRAPHY = False


def make_key() -> "ec.EllipticCurvePrivateKey":
    """Generate RSA public key with short key size, for testing only"""
    return ec.generate_private_key(
        curve=ec.SECP256R1(),
    )


def derive_public_webhook_key(private_key: "ec.EllipticCurvePrivateKey") -> str:
    """Derive public"""
    public_key = private_key.public_key()
    public_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    public_bytes = b"\n".join(public_bytes.splitlines()[1:-1])
    return public_bytes.decode("utf-8")


def sign(
    private_key: "ec.EllipticCurvePrivateKey", timestamp: str, message: str
) -> bytes:
    """Sign message with private key"""
    return private_key.sign(
        (timestamp + message).encode("utf-8"), ec.ECDSA(hashes.SHA256())
    )


class _ClientWithSendGridSignature(ClientWithCsrfChecks):
    private_key = None

    def set_private_key(self, private_key):
        self.private_key = private_key

    def post(self, *args, **kwargs):
        # Timestamp will be a date string, but the exact value doesn't actually
        # matter for verification purposes
        timestamp = "timestamp"
        signature = b64encode(
            sign(
                self.private_key,
                timestamp=timestamp,
                message=json.dumps(kwargs["data"]),
            )
        )
        if kwargs.pop("automatically_set_timestamp_and_signature_headers", True):
            kwargs.setdefault("HTTP_X_TWILIO_EMAIL_EVENT_WEBHOOK_TIMESTAMP", timestamp)
            kwargs.setdefault("HTTP_X_TWILIO_EMAIL_EVENT_WEBHOOK_SIGNATURE", signature)

        webhook_key = derive_public_webhook_key(self.private_key)
        with override_settings(
            ANYMAIL={"SENDGRID_TRACKING_WEBHOOK_VERIFICATION_KEY": webhook_key}
        ):
            return super().post(*args, **kwargs)


ClientWithSendGridSignature = _ClientWithSendGridSignature if HAS_CRYPTOGRAPHY else None
