"""
Sweego-specific inbound email attachment handling.

Sweego's inbound email routing does not include attachment content in webhooks.
Instead, it provides attachment metadata (uuid, name, content_type, size) and
requires a separate API call to fetch the actual attachment content.
"""

import requests
from email.message import EmailMessage

from .exceptions import AnymailAPIError
from .inbound import AnymailInboundMessage


class SweegoLazyAttachment(EmailMessage):
    """
    A lazy-loading attachment for Sweego inbound emails.
    
    The attachment content is only fetched from Sweego's API when accessed.
    This avoids unnecessary API calls if the attachment is never used.
    
    Attributes:
        uuid: Sweego's unique identifier for this attachment
        filename: Original filename
        content_type: MIME type
        size: Size in bytes
        api_url: Base URL for Sweego API
        api_key: API key for authentication
        client_uuid: Sweego client UUID
    """
    
    def __init__(
        self,
        uuid,
        filename,
        content_type,
        size,
        api_url,
        api_key,
        client_uuid,
        content_id=None,
    ):
        super().__init__()
        
        # Sweego attachment metadata
        self.uuid = uuid
        self.filename = filename
        self.size = size
        self.api_url = api_url
        self.api_key = api_key
        self.client_uuid = client_uuid
        
        # Cached content
        self._content = None
        self._fetched = False
        
        # Set email message headers
        self["Content-Type"] = content_type
        self["Content-Disposition"] = (
            "inline" if content_id is not None else "attachment"
        )
        
        if filename:
            self.set_param("name", filename, header="Content-Type")
            self.set_param("filename", filename, header="Content-Disposition")
        
        if content_id is not None:
            from .utils import angle_wrap
            self["Content-ID"] = angle_wrap(content_id)
    
    def _fetch_content(self):
        """
        Fetch the attachment content from Sweego's API.
        
        Makes a GET request to:
        https://api.sweego.io/clients/{client_uuid}/domains/inbound/attachments/{uuid}
        
        Raises:
            AnymailAPIError: If the API request fails
        """
        if self._fetched:
            return
        
        url = (
            f"{self.api_url}/clients/{self.client_uuid}"
            f"/domains/inbound/attachments/{self.uuid}"
        )
        
        headers = {
            "Api-Key": self.api_key,
            "Accept": "application/octet-stream",  # Get raw binary content
        }
        
        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            self._content = response.content
            self._fetched = True
        except requests.RequestException as e:
            raise AnymailAPIError(
                f"Failed to fetch Sweego attachment {self.uuid}: {e}",
                backend=None,
                email_message=None,
                payload=None,
            ) from e
    
    def get_payload(self, i=None, decode=False):
        """
        Override to fetch content on first access.
        
        This method is called by get_content(), get_content_bytes(), etc.
        """
        if not self._fetched:
            self._fetch_content()
        
        if self._content is None:
            return None
        
        # If decode=True, the caller wants the decoded content
        # For binary attachments, we just return the raw bytes
        if decode:
            return self._content
        
        # If decode=False, we need to return the content in a way
        # that email.message.EmailMessage expects
        return self._content
    
    def set_payload(self, payload, charset=None):
        """
        Override to cache the content without fetching.
        
        This allows the attachment to be pre-populated if needed.
        """
        self._content = payload
        self._fetched = True
    
    def get_content_bytes(self):
        """Get the raw attachment content as bytes."""
        if not self._fetched:
            self._fetch_content()
        return self._content
    
    def get_content_text(self, encoding=None):
        """
        Get the attachment content as text.
        
        Only appropriate for text/* content types.
        """
        content = self.get_content_bytes()
        if content is None:
            return None
        
        if encoding is None:
            # Try to get encoding from Content-Type charset parameter
            charset = self.get_param("charset")
            encoding = charset if charset else "utf-8"
        
        return content.decode(encoding, errors="replace")
    
    def get_filename(self):
        """Get the attachment filename."""
        # Try Content-Disposition first (standard)
        filename = self.get_param("filename", header="Content-Disposition")
        if filename:
            return filename
        
        # Fall back to Content-Type name parameter
        filename = self.get_param("name", header="Content-Type")
        if filename:
            return filename
        
        # Fall back to our stored filename
        return self.filename
    
    def is_inline(self):
        """Check if this attachment is inline (e.g., embedded image)."""
        return self.get_content_disposition() == "inline"
    
    def __repr__(self):
        return (
            f"<SweegoLazyAttachment: {self.filename} "
            f"({self.get_content_type()}, {self.size} bytes, "
            f"fetched={self._fetched})>"
        )


def construct_sweego_lazy_attachment(
    attachment_data,
    api_url,
    api_key,
    client_uuid,
):
    """
    Construct a lazy attachment from Sweego webhook attachment metadata.
    
    Args:
        attachment_data: Dict with keys 'uuid', 'name', 'content_type', 'size'
        api_url: Base URL for Sweego API (e.g., 'https://api.sweego.io')
        api_key: API key for authentication
        client_uuid: Sweego client UUID
    
    Returns:
        SweegoLazyAttachment instance
    """
    return SweegoLazyAttachment(
        uuid=attachment_data["uuid"],
        filename=attachment_data.get("name", "attachment"),
        content_type=attachment_data.get("content_type", "application/octet-stream"),
        size=attachment_data.get("size", 0),
        api_url=api_url,
        api_key=api_key,
        client_uuid=client_uuid,
        content_id=attachment_data.get("content_id"),  # For inline images
    )
