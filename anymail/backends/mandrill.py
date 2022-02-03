import warnings
from datetime import datetime

from ..exceptions import AnymailRequestsAPIError, AnymailWarning
from ..message import AnymailRecipientStatus, ANYMAIL_STATUSES
from ..utils import last, combine, get_anymail_setting

from .base_requests import AnymailRequestsBackend, RequestsPayload


class EmailBackend(AnymailRequestsBackend):
    """
    Mandrill API Email Backend
    """

    esp_name = "Mandrill"

    def __init__(self, **kwargs):
        """Init options from Django settings"""
        esp_name = self.esp_name
        self.api_key = get_anymail_setting('api_key', esp_name=esp_name, kwargs=kwargs, allow_bare=True)
        api_url = get_anymail_setting('api_url', esp_name=esp_name, kwargs=kwargs,
                                      default="https://mandrillapp.com/api/1.0")
        if not api_url.endswith("/"):
            api_url += "/"
        super().__init__(api_url, **kwargs)

    def build_message_payload(self, message, defaults):
        return MandrillPayload(message, defaults, self)

    def parse_recipient_status(self, response, payload, message):
        parsed_response = self.deserialize_json_response(response, payload, message)
        recipient_status = {}
        try:
            # Mandrill returns a list of { email, status, _id, reject_reason } for each recipient
            for item in parsed_response:
                email = item['email']
                status = item['status']
                if status not in ANYMAIL_STATUSES:
                    status = 'unknown'
                message_id = item.get('_id', None)  # can be missing for invalid/rejected recipients
                recipient_status[email] = AnymailRecipientStatus(message_id=message_id, status=status)
        except (KeyError, TypeError) as err:
            raise AnymailRequestsAPIError("Invalid Mandrill API response format",
                                          email_message=message, payload=payload, response=response,
                                          backend=self) from err
        return recipient_status


class DjrillDeprecationWarning(AnymailWarning, DeprecationWarning):
    """Warning for features carried over from Djrill that will be removed soon"""


def encode_date_for_mandrill(dt):
    """Format a datetime for use as a Mandrill API date field

    Mandrill expects "YYYY-MM-DD HH:MM:SS" in UTC
    """
    if isinstance(dt, datetime):
        dt = dt.replace(microsecond=0)
        if dt.utcoffset() is not None:
            dt = (dt - dt.utcoffset()).replace(tzinfo=None)
        return dt.isoformat(' ')
    else:
        return dt


class MandrillPayload(RequestsPayload):

    def __init__(self, *args, **kwargs):
        self.esp_extra = {}  # late-bound in serialize_data
        super().__init__(*args, **kwargs)

    def get_api_endpoint(self):
        if 'template_name' in self.data:
            return "messages/send-template.json"
        else:
            return "messages/send.json"

    def serialize_data(self):
        self.process_esp_extra()
        if self.is_batch():
            # hide recipients from each other
            self.data['message']['preserve_recipients'] = False
        return self.serialize_json(self.data)

    #
    # Payload construction
    #

    def init_payload(self):
        self.data = {
            "key": self.backend.api_key,
            "message": {},
        }

    def set_from_email(self, email):
        if getattr(self.message, "use_template_from", False):
            self.deprecation_warning('message.use_template_from', 'message.from_email = None')
        else:
            self.data["message"]["from_email"] = email.addr_spec
            if email.display_name:
                self.data["message"]["from_name"] = email.display_name

    def add_recipient(self, recipient_type, email):
        assert recipient_type in ["to", "cc", "bcc"]
        recipient_data = {"email": email.addr_spec, "type": recipient_type}
        if email.display_name:
            recipient_data["name"] = email.display_name
        to_list = self.data["message"].setdefault("to", [])
        to_list.append(recipient_data)

    def set_subject(self, subject):
        if getattr(self.message, "use_template_subject", False):
            self.deprecation_warning('message.use_template_subject', 'message.subject = None')
        else:
            self.data["message"]["subject"] = subject

    def set_reply_to(self, emails):
        if emails:
            reply_to = ", ".join([str(email) for email in emails])
            self.data["message"].setdefault("headers", {})["Reply-To"] = reply_to

    def set_extra_headers(self, headers):
        self.data["message"].setdefault("headers", {}).update(headers)

    def set_text_body(self, body):
        self.data["message"]["text"] = body

    def set_html_body(self, body):
        if "html" in self.data["message"]:
            # second html body could show up through multiple alternatives, or html body + alternative
            self.unsupported_feature("multiple html parts")
        self.data["message"]["html"] = body

    def add_attachment(self, attachment):
        if attachment.inline:
            field = "images"
            name = attachment.cid
        else:
            field = "attachments"
            name = attachment.name or ""
        self.data["message"].setdefault(field, []).append({
            "type": attachment.mimetype,
            "name": name,
            "content": attachment.b64content
        })

    def set_envelope_sender(self, email):
        # Only the domain is used
        self.data["message"]["return_path_domain"] = email.domain

    def set_metadata(self, metadata):
        self.data["message"]["metadata"] = metadata

    def set_send_at(self, send_at):
        self.data["send_at"] = encode_date_for_mandrill(send_at)

    def set_tags(self, tags):
        self.data["message"]["tags"] = tags

    def set_track_clicks(self, track_clicks):
        self.data["message"]["track_clicks"] = track_clicks

    def set_track_opens(self, track_opens):
        self.data["message"]["track_opens"] = track_opens

    def set_template_id(self, template_id):
        self.data["template_name"] = template_id
        self.data.setdefault("template_content", [])  # Mandrill requires something here

    def set_merge_data(self, merge_data):
        self.data['message']['merge_vars'] = [
            {'rcpt': rcpt, 'vars': [{'name': key, 'content': rcpt_data[key]}
                                    for key in sorted(rcpt_data.keys())]}  # sort for testing reproducibility
            for rcpt, rcpt_data in merge_data.items()
        ]

    def set_merge_global_data(self, merge_global_data):
        self.data['message']['global_merge_vars'] = [
            {'name': var, 'content': value}
            for var, value in merge_global_data.items()
        ]

    def set_merge_metadata(self, merge_metadata):
        # recipient_metadata format is similar to, but not quite the same as, merge_vars:
        self.data['message']['recipient_metadata'] = [
            {'rcpt': rcpt, 'values': rcpt_data}
            for rcpt, rcpt_data in merge_metadata.items()
        ]

    def set_esp_extra(self, extra):
        # late bind in serialize_data, so that obsolete Djrill attrs can contribute
        self.esp_extra = extra

    def process_esp_extra(self):
        if self.esp_extra is not None and len(self.esp_extra) > 0:
            esp_extra = self.esp_extra
            # Convert pythonic template_content dict to Mandrill name/content list
            try:
                template_content = esp_extra['template_content']
            except KeyError:
                pass
            else:
                if hasattr(template_content, 'items'):  # if it's dict-like
                    if esp_extra is self.esp_extra:
                        esp_extra = self.esp_extra.copy()  # don't modify caller's value
                    esp_extra['template_content'] = [
                        {'name': var, 'content': value}
                        for var, value in template_content.items()]
            # Convert pythonic recipient_metadata dict to Mandrill rcpt/values list
            try:
                recipient_metadata = esp_extra['message']['recipient_metadata']
            except KeyError:
                pass
            else:
                if hasattr(recipient_metadata, 'keys'):  # if it's dict-like
                    if esp_extra['message'] is self.esp_extra['message']:
                        esp_extra['message'] = self.esp_extra['message'].copy()  # don't modify caller's value
                    # For testing reproducibility, we sort the recipients
                    esp_extra['message']['recipient_metadata'] = [
                        {'rcpt': rcpt, 'values': recipient_metadata[rcpt]}
                        for rcpt in sorted(recipient_metadata.keys())]
            # Merge esp_extra with payload data: shallow merge within ['message'] and top-level keys
            self.data.update({k: v for k, v in esp_extra.items() if k != 'message'})
            try:
                self.data['message'].update(esp_extra['message'])
            except KeyError:
                pass

    # Djrill deprecated message attrs

    def deprecation_warning(self, feature, replacement=None):
        msg = "Djrill's `%s` will be removed in an upcoming Anymail release." % feature
        if replacement:
            msg += " Use `%s` instead." % replacement
        warnings.warn(msg, DjrillDeprecationWarning)

    def deprecated_to_esp_extra(self, attr, in_message_dict=False):
        feature = "message.%s" % attr
        if in_message_dict:
            replacement = "message.esp_extra = {'message': {'%s': <value>}}" % attr
        else:
            replacement = "message.esp_extra = {'%s': <value>}" % attr
        self.deprecation_warning(feature, replacement)

    esp_message_attrs = (
        ('async', last, None),
        ('ip_pool', last, None),
        ('from_name', last, None),  # overrides display name parsed from from_email above
        ('important', last, None),
        ('auto_text', last, None),
        ('auto_html', last, None),
        ('inline_css', last, None),
        ('url_strip_qs', last, None),
        ('tracking_domain', last, None),
        ('signing_domain', last, None),
        ('return_path_domain', last, None),
        ('merge_language', last, None),
        ('preserve_recipients', last, None),
        ('view_content_link', last, None),
        ('subaccount', last, None),
        ('google_analytics_domains', last, None),
        ('google_analytics_campaign', last, None),
        ('global_merge_vars', combine, None),
        ('merge_vars', combine, None),
        ('recipient_metadata', combine, None),
        ('template_name', last, None),
        ('template_content', combine, None),
    )

    def set_async(self, is_async):
        self.deprecated_to_esp_extra('async')
        self.esp_extra['async'] = is_async

    def set_ip_pool(self, ip_pool):
        self.deprecated_to_esp_extra('ip_pool')
        self.esp_extra['ip_pool'] = ip_pool

    def set_global_merge_vars(self, global_merge_vars):
        self.deprecation_warning('message.global_merge_vars', 'message.merge_global_data')
        self.set_merge_global_data(global_merge_vars)

    def set_merge_vars(self, merge_vars):
        self.deprecation_warning('message.merge_vars', 'message.merge_data')
        self.set_merge_data(merge_vars)

    def set_return_path_domain(self, domain):
        self.deprecation_warning('message.return_path_domain', 'message.envelope_sender')
        self.esp_extra.setdefault('message', {})['return_path_domain'] = domain

    def set_template_name(self, template_name):
        self.deprecation_warning('message.template_name', 'message.template_id')
        self.set_template_id(template_name)

    def set_template_content(self, template_content):
        self.deprecated_to_esp_extra('template_content')
        self.esp_extra['template_content'] = template_content

    def set_recipient_metadata(self, recipient_metadata):
        self.deprecated_to_esp_extra('recipient_metadata', in_message_dict=True)
        self.esp_extra.setdefault('message', {})['recipient_metadata'] = recipient_metadata

    # Set up simple set_<attr> functions for any missing esp_message_attrs attrs
    # (avoids dozens of simple `self.data["message"][<attr>] = value` functions)

    @classmethod
    def define_message_attr_setters(cls):
        for (attr, _, _) in cls.esp_message_attrs:
            setter_name = 'set_%s' % attr
            try:
                getattr(cls, setter_name)
            except AttributeError:
                setter = cls.make_setter(attr, setter_name)
                setattr(cls, setter_name, setter)

    @staticmethod
    def make_setter(attr, setter_name):
        # sure wish we could use functools.partial to create instance methods (descriptors)
        def setter(self, value):
            self.deprecated_to_esp_extra(attr, in_message_dict=True)
            self.esp_extra.setdefault('message', {})[attr] = value
        setter.__name__ = setter_name
        return setter


MandrillPayload.define_message_attr_setters()
