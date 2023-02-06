import warnings

from django.http import HttpResponse
from django.utils.crypto import constant_time_compare
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import View

from ..exceptions import AnymailInsecureWebhookWarning, AnymailWebhookValidationFailure
from ..utils import collect_all_methods, get_anymail_setting, get_request_basic_auth


# Mixin note: Django's View.__init__ doesn't cooperate with chaining,
# so all mixins that need __init__ must appear before View in MRO.
class AnymailCoreWebhookView(View):
    """Common view for processing ESP event webhooks

    ESP-specific implementations will need to implement parse_events.

    ESP-specific implementations should generally subclass
    AnymailBaseWebhookView instead, to pick up basic auth.
    They may also want to implement validate_request
    if additional security is available.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.validators = collect_all_methods(self.__class__, "validate_request")

    # Subclass implementation:

    # Where to send events: either ..signals.inbound or ..signals.tracking
    signal = None

    def validate_request(self, request):
        """Check validity of webhook post, or raise AnymailWebhookValidationFailure.

        AnymailBaseWebhookView includes basic auth validation.
        Subclasses can implement (or provide via mixins) if the ESP supports
        additional validation (such as signature checking).

        *All* definitions of this method in the class chain (including mixins)
        will be called. There is no need to chain to the superclass.
        (See self.run_validators and collect_all_methods.)

        Security note: use django.utils.crypto.constant_time_compare for string
        comparisons, to avoid exposing your validation to a timing attack.
        """
        # if not constant_time_compare(request.POST['signature'], expected_signature):
        #     raise AnymailWebhookValidationFailure("...message...")
        # (else just do nothing)
        pass

    def parse_events(self, request):
        """Return a list of normalized AnymailWebhookEvent extracted from ESP post data.

        Subclasses must implement.
        """
        raise NotImplementedError()

    # HTTP handlers (subclasses shouldn't need to override):

    http_method_names = ["post", "head", "options"]

    @method_decorator(csrf_exempt)
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)

    def head(self, request, *args, **kwargs):
        # Some ESPs verify the webhook with a HEAD request at configuration time
        return HttpResponse()

    def post(self, request, *args, **kwargs):
        # Normal Django exception handling will do the right thing:
        # - AnymailWebhookValidationFailure will turn into an HTTP 400 response
        #   (via Django SuspiciousOperation handling)
        # - Any other errors (e.g., in signal dispatch) will turn into HTTP 500
        #   responses (via normal Django error handling). ESPs generally
        #   treat that as "try again later".
        self.run_validators(request)
        events = self.parse_events(request)
        esp_name = self.esp_name
        for event in events:
            self.signal.send(sender=self.__class__, event=event, esp_name=esp_name)
        return HttpResponse()

    # Request validation (subclasses shouldn't need to override):

    def run_validators(self, request):
        for validator in self.validators:
            validator(self, request)

    @property
    def esp_name(self):
        """
        Read-only name of the ESP for this webhook view.

        Subclasses must override with class attr. E.g.:
            esp_name = "Postmark"
            esp_name = "SendGrid"  # (use ESP's preferred capitalization)
        """
        raise NotImplementedError(
            "%s.%s must declare esp_name class attr"
            % (self.__class__.__module__, self.__class__.__name__)
        )


class AnymailBasicAuthMixin(AnymailCoreWebhookView):
    """Implements webhook basic auth as mixin to AnymailCoreWebhookView."""

    # Whether to warn if basic auth is not configured.
    # For most ESPs, basic auth is the only webhook security,
    # so the default is True. Subclasses can set False if
    # they enforce other security (like signed webhooks).
    warn_if_no_basic_auth = True

    # List of allowable HTTP basic-auth 'user:pass' strings.
    # (Declaring class attr allows override by kwargs in View.as_view.):
    basic_auth = None

    def __init__(self, **kwargs):
        self.basic_auth = get_anymail_setting(
            "webhook_secret",
            default=[],
            # no esp_name -- auth is shared between ESPs
            kwargs=kwargs,
        )

        # Allow a single string:
        if isinstance(self.basic_auth, str):
            self.basic_auth = [self.basic_auth]
        if self.warn_if_no_basic_auth and len(self.basic_auth) < 1:
            warnings.warn(
                "Your Anymail webhooks are insecure and open to anyone on the web. "
                "You should set WEBHOOK_SECRET in your ANYMAIL settings. "
                "See 'Securing webhooks' in the Anymail docs.",
                AnymailInsecureWebhookWarning,
            )
        super().__init__(**kwargs)

    def validate_request(self, request):
        """If configured for webhook basic auth, validate request has correct auth."""
        if self.basic_auth:
            request_auth = get_request_basic_auth(request)
            # Use constant_time_compare to avoid timing attack on basic auth. (It's OK
            # that any() can terminate early: we're not trying to protect how many auth
            # strings are allowed, just the contents of each individual auth string.)
            auth_ok = any(
                constant_time_compare(request_auth, allowed_auth)
                for allowed_auth in self.basic_auth
            )
            if not auth_ok:
                raise AnymailWebhookValidationFailure(
                    "Missing or invalid basic auth in Anymail %s webhook"
                    % self.esp_name
                )


class AnymailBaseWebhookView(AnymailBasicAuthMixin, AnymailCoreWebhookView):
    """
    Abstract base class for most webhook views, enforcing HTTP basic auth security
    """

    pass
