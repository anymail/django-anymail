.. _intl-email:

International email (Unicode)
=============================

Anymail's goal is to fully support non-ASCII Unicode characters everywhere
permitted by the relevant email specifications.

.. sidebar:: tl;dr

    If you want to work with email using characters other than 7-bit ASCII,
    review the "Limitations and quirks" section of your ESP's page in
    Anymail's :ref:`supported-esps` documentation.

Using Unicode characters in email involves a confusing patchwork of standards,
with multiple, sometimes conflicting revisions. But you shouldn't need to
understand all of that: you're paying your ESP for their expertise.
Unfortunately, ESPs (and the libraries they build on) often find the world
of email specifications as complex as you would.
**ESP bugs involving non-ASCII characters are extremely common.**

As of vNext (December 2025), Anymail's developers have performed detailed
Unicode handling tests on each "fully supported" ESP. Similar tests will be
run on new ESPs during their initial integration.

For tests that uncover problems with the ESP's API, we:

* Report the issue to the ESP (if they have a way to report API bugs)

* Try to implement a workaround in Anymail's code, if possible

* If a workaround is not possible, document the behavior on Anymail's page
  for that ESP (see :ref:`supported-esps`) under "Limitations and quirks"

* In rare cases, raise an Anymail error to help you avoid particularly
  problematic ESP behavior that could interfere with message delivery

This page goes into more detail on handling non-ASCII characters in specific
parts of an email message:

.. contents::
    :local:
    :depth: 1

.. _eai:
.. _intl-email-address:
.. _intl-display-name:

Email addresses
---------------

An email address includes at least a mailbox and domain, and possibly
a human-friendly "display name":

    ``mailbox@domain`` or ``"Display Name" <mailbox@domain>``

Each of these three parts uses a different specification for handling non-ASCII
characters, making it especially confusing. (In email standards, the *mailbox*
is sometimes called *local-part* or *username*. And *mailbox\@domain* is called
an *addr-spec*.)

Display name
    ESP bugs in display name handling are pretty common, especially if you mix
    Unicode characters and commas or other characters that have special meaning
    in an address header.

    Anymail has workarounds for *most* of the bugs, but be sure to check your
    ESP's "Limitations and quirks" under :ref:`supported-esps`.

Mailbox (EAI)
    Unicode in an email mailbox is a relatively recent standard and not yet
    widely adopted. This is part of "EAI"---email address internationalization
    (defined in :rfc:`6532` and its peer specifications).

    ESP support for EAI is mixed: some allow Unicode in any email mailbox, some
    support it for recipients but not the *From* address, and some reject EAI
    completely. A small number of ESPs accept Unicode mailboxes in API
    requests but generate undeliverable messages; Anymail raises an error in
    this situation.

    If you want to support EAI in your Django app, it's important to review
    your ESP-specific "Limitations and quirks" under :ref:`supported-esps`.
    Also note that most browsers' ``<input type="email">`` controls reject EAI
    emails as invalid. So does Django's own EmailValidator (Django
    `ticket-27029`_) and SMTP EmailBackend (`ticket-35714`_).

Domain
    Most ESPs don't directly support Unicode characters in an email address
    domain name. So for consistency, Anymail (by default) encodes non-ASCII
    email domains for *all* ESPs before calling their APIs, using IDNA 2008.
    But this is a complex topic, covered in detail in the next section:
    :ref:`idna`.

    .. versionchanged:: vNext

        Earlier Anymail releases encoded email domains using IDNA 2003.

.. _ticket-27029: https://code.djangoproject.com/ticket/27029
.. _ticket-35714: https://code.djangoproject.com/ticket/35714

.. _safe-email-address:

.. caution::

    **Never** try to construct an email address from parts using string
    formatting. This opens you to an **email header injection vulnerability**
    (similar to SQL or HTML injection). Attackers will exploit it to make your
    app send email to or from addresses you didn't intend.

    .. code-block:: python

        # SECURITY VULNERABILITY: never do this!
        address = f"{name} <{email}>"  # allows email header injection

    Instead, you can safely construct a formatted address from a name and
    email using Python's :class:`email.headerregistry.Address` object:

    .. code-block:: python

        # This is the safe way to combine a name and email:
        from email.headerregistry import Address

        address = str(Address(display_name=name, addr_spec=email))


.. _idna:
.. _intl-domain:

Email address domains (IDNA)
----------------------------

An international domain name (IDN, with Unicode characters) must be converted
to ASCII for DNS lookup: e.g., ``テスト.example.jp`` becomes ``xn--zckzah.example.jp``.
This conversion is known as IDNA (IDN for Applications), and uses the special
prefix *xn-\-* with "Punycode" encoded ASCII.

You'll find a mix of IDNA approaches currently in use by different email
clients and services:

* The original `IDNA 2003`_, now considered obsolete (but email infrastructure
  moves slowly)

* The updated `IDNA 2008`_, which added support for characters used by several
  active languages (but removed support for symbols---including emoji---that
  were allowed before)

* Unicode's `UTS46`_ standard, which tries to strike a practical balance
  between the two IDNA versions (and is used by all modern web browsers)

Most ESPs don't handle IDNA, and those that do vary on their choice of encoding.
For consistency, Anymail normally encodes IDNs in email addresses before
sending them through your ESP.

By default, Anymail uses IDNA 2008 with UTS46 preprocessing. IDNA 2008 supports
newer domains, and is unlikely to cause problems for other domains used in
real-world email addresses.  (UTS46 "preprocessing" provides case-insensitivity
users expect, but rejects emoji domains that browsers would allow.)

If you need different behavior, you can change IDNA encoders or defer encoding
to your ESP.

.. versionchanged:: vNext

    Earlier Anymail releases used IDNA 2003 encoding, matching Django.
    (Django's SMTP EmailBackend still uses IDNA 2003.)

.. _IDNA 2003: https://datatracker.ietf.org/doc/html/rfc3490.html
.. _IDNA 2008: https://datatracker.ietf.org/doc/html/rfc5890.html
.. _UTS46: https://www.unicode.org/reports/tr46/


.. setting:: ANYMAIL_IDNA_ENCODER

.. rubric:: IDNA_ENCODER

.. versionadded:: vNext

Controls the IDNA encoding used for email domains that contain non-ASCII
characters. The default is ``"idna2008"``. To select a different option,
in your settings.py add:

  .. code-block:: python

      ANYMAIL = {
          ...
          "IDNA_ENCODER": "uts46",
      }


The value of ``IDNA_ENCODER`` can be:

* ``"idna2008"`` (default): Uses IDNA 2008 with UTS46 preprocessing

  Recommended for most uses. Handles newer domains enabled by IDNA 2008.
  But it will reject some existing domains that IDNA 2003 allowed. (If this
  causes compatibility issues that affect you, consider ``"uts46"`` as an
  alternative.)

  Implemented with the widely-used, third-party :pypi:`idna` package, which
  is included with django-anymail installation.

* ``"idna2003"``: Uses obsolete IDNA 2003

  Use *only* if you need exact compatibility with Django's SMTP EmailBackend
  or backwards compatibility with earlier versions of Anymail. IDNA 2003
  cannot handle newer domains that were enabled by IDNA 2008.

  IDNA 2003 is built into Python and requires no additional libraries.

* ``"uts46"``: Uses UTS46 (full, not just preprocessing)

  Consider using if you have problems with IDNA 2008 rejecting certain domains.
  UTS46 is what all current web browsers use for IDN encoding. It combines
  IDNA 2008's support for newer domains with somewhat relaxed restrictions on
  allowable domains.

  This implementation uses *nontransitional* processing, the current standard.
  If you want UTS46 with obsolete *transitional* compatibility mapping, use a
  custom function as shown below. (The difference is explained in
  `UTS46 section 1.3.2 Deviations`_.)

  Requires the experimental, third-party :pypi:`uts46` package. You can
  install this as an optional extra with django-anymail:
  :command:`pip install "django-anymail[<your-esp>,uts46]"`

* ``"none"``: Performs no IDNA encoding

  Calls your ESP with email addresses using the original, unencoded Unicode IDN.
  (Note this is the string ``"none"``, not the `None` value.)

  May be helpful if you are also calling your ESP's APIs directly and want to
  avoid Anymail encoding domain names differently. Your ESP must support IDN
  encoding. (If not, you'll either get an API error, a bounce, or possibly
  the message will just disappear without a trace.)

* **Custom function:** A callable or string dotted import path to a function

  The custom encoder function must take and return string domain names
  (don't return bytes). It should raise :exc:`!ValueError` (or a subclass like
  :exc:`!UnicodeError`) for encoding problems.

  For example, if you wanted to use UTS46 with obsolete transitional processing:

      .. code-block:: python

          # settings.py:
          ANYMAIL = {
              ...
              "IDNA_ENCODER": "path.to.custom.uts46_transitional",
          }

          # path/to/custom.py:
          import uts46

          def uts46_transitional(domain: str) -> str:
              return uts46.encode(domain, transitional_processing=True).decode("ascii")

.. _UTS46 section 1.3.2 Deviations: https://www.unicode.org/reports/tr46/#Deviations

.. _intl-subject:
.. _intl-header:

Subjects and other headers
--------------------------

All ESPs supported by Anymail correctly handle non-ASCII characters in
the email subject.

Nearly all ESPs correctly handle Unicode in other email header fields such as
custom headers. Anymail implements workarounds for *most* of the ones that
don't, but check your ESP's "Limitations and quirks" in :ref:`supported-esps`.

(Email specifications do not permit Unicode characters in custom header
*names,* only in the values.)

.. _intl-body:

Body text
---------

All ESPs supported by Anymail correctly handle non-ASCII characters in
plaintext and HTML message bodies.


.. _intl-attachment:

Attachments
-----------

Attachment filenames
    The bad news: nearly all of Anymail's supported ESPs have bugs in how they
    handle non-ASCII attachment filenames and generate technically out-of-spec
    attachment headers. And Anymail generally can't work around ESP filename
    encoding bugs.

    The good news: bugs in attachment filename encoding are so common that many
    email apps are tolerant of the errors and display the names as intended.

    A few ESPs don't identify what character set they use for non-ASCII
    filenames, which causes them to display incorrectly in some email apps.
    Check your ESP's "Limitations and quirks" to see, and if you want to ensure
    no recipient will see garbled filenames, stick to ASCII-only.

    Otherwise, as a general rule it should be safe to use Unicode attachment
    filenames (and rely on email client workarounds for the ESP spec violations).

Attachment text content
    In text attachments nearly all of Anymail's supported ESPs correctly handle
    non-ASCII characters. For a few ESPs whose APIs don't have a way to specify
    text attachment character set, Anymail uses utf-8. This is a reasonable
    choice for modern email clients, but there is a slight risk of `mojibake`_
    in very old email apps.

As always, check for exceptions under "Limitations and quirks" on Anymail's
page for your ESP, in :ref:`supported-esps` .

.. _mojibake: https://en.wikipedia.org/wiki/Mojibake


What Anymail tests
------------------

For interested readers (or ESP engineers), here is what Anymail looks for when
testing Unicode handling. Italicized terms are from the various RFCs.

*   **Email addresses** (:mailheader:`From/To/Cc/Bcc/Reply-To`)

    *   *display-name:* A non-ASCII *display-name* must be sent using an
        :rfc:`2047` *encoded-word*. An ASCII-only *display-name* that contains
        *specials* (like comma or parentheses) must be sent as an :rfc:`5322`
        *quoted-string.*

    *   *local-part:* A non-ASCII *local-part* (EAI) can only be sent to an
        SMTP server that supports the smtputf8 extension, :rfc:`6531`. Per
        :rfc:`6532` it must appear in headers as 8-bit utf-8. (There is no
        valid 7-bit encoding for a Unicode *local-part*.)

    *   *domain:* A non-ASCII *domain* (IDN) must be encoded, ideally with
        `IDNA 2008`_ or `UTS46`_ non-transitional. Anymail's tests also treat
        `IDNA 2003`_ or UTS46 transitional as acceptable, though outdated. IDNA
        must be applied to both SMTP envelope addresses and (unless the
        receiving server supports smtputf8) domains in email header fields.

        (Because Anymail by default provides its own IDNA encoding, whether and
        how each ESP handles IDNs is noted but not treated as a limitation.)

    Common Unicode address mistakes:

    *   Wrapping an *encoded-word* in a *quoted-string*; using an *encoded-word*
        for the *local-part* and/or *domain* (*addr-spec*); encoding the entire
        header as a single *encoded-word*---all "must not" per :rfc:`2047`
        section 5(3)

    *   Returning API errors or generating invalid headers when a *display-name*
        includes both *specials* and Unicode characters

    *   Handling :mailheader:`Reply-To` as an *unstructured header* rather than
        a *structured* address header

    *   Sending a raw, 8-bit utf-8 *addr-spec* without verifying the receiving
        SMTP server supports smtputf8

*   **Subject and custom headers:** Non-ASCII must be sent using an :rfc:`2047`
    *encoded-word*.

    (All supported ESPs handle Unicode subjects correctly.)

    Common custom header mistakes:

    *   Wrapping an *encoded-word* in a *quoted-string*---a "must not" per
        :rfc:`2047` section 5(3)

    *   Sending raw, 8-bit utf-8 (without verifying the receiving SMTP server
        supports smtputf8)

*   **Body parts** (text and html): The non-ASCII encoding must be identified with
    a ``charset`` parameter in the :mailheader:`Content-Type` header. The
    correct :mailheader:`Content-Transfer-Encoding` header must be present.

    (All supported ESPs handle Unicode body parts correctly.)

*   **Attachments**

    *   Filenames: In the :mailheader:`Content-Disposition` and
        :mailheader:`Content-Type` attachment headers, MIME parameters like
        ``filename`` and ``name`` must use :rfc:`2231` (section 4) parameter
        value syntax for non-ASCII characters. E.g. (note the ``*=utf-8'...``,
        *not* RFC 2047's ``=?utf-8?...``):

            :samp:`Content-Disposition: attachment; filename*=utf-8''skr%C3%A1.txt`

    *   Content: as with body parts, text/* attachments must identify the
        specific non-ASCII encoding used with a ``charset`` parameter in the
        :mailheader:`Content-Type` header.

    Common attachment mistakes:

    *   Using an *encoded-word* in the ``filename`` or ``name`` parameter---a
        "must not" in MIME parameter values per :rfc:`2047` section 5(3)
        (though many email apps tolerate this error)

        (Using RFC 2047 here might be a misapplication of the obsolete
        :rfc:`2388`, which applied only to HTTP multipart/form-data, *not*
        attachments in a multipart/mixed email message.)

    *   Sending raw, 8-bit utf-8 in the MIME header, which leads to mojibake
        filenames in email clients that assume some other encoding

        (Using 8-bit here might be a misapplication of :rfc:`7578`, which
        applies only to HTTP multipart/form-data, *not* attachments in a
        multipart/mixed email message.)

    *   Omitting the ``charset`` MIME parameter for text attachments, or not
        providing a way for API users to specify it, or overriding one given
        in the API call (without re-encoding the attachment content to
        match)---any of which can result in mojibake content
