from base64 import b64encode

from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from django.test import override_settings

from tests.utils import ClientWithCsrfChecks


def make_key():
    """Generate RSA public key with short key size, for testing only"""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=512,
    )
    return private_key


def derive_public_webhook_key(private_key):
    """Derive public """
    public_key = private_key.public_key()
    public_bytes = public_key.public_bytes(encoding=serialization.Encoding.PEM, format=serialization.PublicFormat.SubjectPublicKeyInfo)
    public_bytes = b'\n'.join(public_bytes.splitlines()[1:-1])
    return public_bytes.decode('utf-8')


def sign(private_key, message):
    """Sign message with private key"""
    signature = private_key.sign(message, padding.PKCS1v15(), hashes.SHA1())
    return signature


class ClientWithPostalSignature(ClientWithCsrfChecks):
    private_key = None

    def set_private_key(self, private_key):
        self.private_key = private_key

    def post(self, *args, **kwargs):
        signature = b64encode(sign(self.private_key, kwargs['data'].encode('utf-8')))
        kwargs.setdefault('HTTP_X_POSTAL_SIGNATURE', signature)

        webhook_key = derive_public_webhook_key(self.private_key)
        with override_settings(ANYMAIL={'POSTAL_WEBHOOK_KEY': webhook_key}):
            return super().post(*args, **kwargs)
