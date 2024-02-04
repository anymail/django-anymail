from base64 import b64encode

from django.test import override_settings

from anymail.exceptions import AnymailImproperlyInstalled, _LazyError

try:
    from nacl.signing import SigningKey
except ImportError:
    # This will be raised if signing is attempted (and pynacl wasn't found)
    SigningKey = _LazyError(
        AnymailImproperlyInstalled(missing_package="pynacl", install_extra="mailpace")
    )

from tests.utils import ClientWithCsrfChecks


def make_key():
    """Generate key, for testing only"""
    return SigningKey.generate()


def derive_public_webhook_key(private_key):
    """Derive public key from private key, in base64 as per MailPace spec"""
    verify_key_bytes = private_key.verify_key.encode()
    return b64encode(verify_key_bytes).decode()


# Returns a signature, as a byte string that has been Base64 encoded
# As per MailPace docs
def sign(private_key, message):
    """Sign message with private key"""
    signature_bytes = private_key.sign(message).signature
    return b64encode(signature_bytes).decode("utf-8")


class _ClientWithMailPaceSignature(ClientWithCsrfChecks):
    private_key = None

    def set_private_key(self, private_key):
        self.private_key = private_key

    def post(self, *args, **kwargs):
        data = kwargs.get("data", "").encode("utf-8")

        headers = kwargs.setdefault("headers", {})
        if "X-MailPace-Signature" not in headers:
            signature = sign(self.private_key, data)
            headers["X-MailPace-Signature"] = signature

        webhook_key = derive_public_webhook_key(self.private_key)
        with override_settings(ANYMAIL={"MAILPACE_WEBHOOK_KEY": webhook_key}):
            # Django 4.2+ test Client allows headers=headers;
            # before that, must convert to HTTP_ args:
            return super().post(
                *args,
                **kwargs,
                **{
                    f"HTTP_{header.upper().replace('-', '_')}": value
                    for header, value in headers.items()
                },
            )


ClientWithMailPaceSignature = _ClientWithMailPaceSignature
