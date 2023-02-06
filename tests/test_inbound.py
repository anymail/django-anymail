import quopri
from base64 import b64encode
from email.utils import collapse_rfc2231_value
from textwrap import dedent

from django.core.mail import SafeMIMEText
from django.test import SimpleTestCase

from anymail.inbound import AnymailInboundMessage

from .utils import SAMPLE_IMAGE_FILENAME, sample_email_path, sample_image_content

SAMPLE_IMAGE_CONTENT = sample_image_content()


class AnymailInboundMessageConstructionTests(SimpleTestCase):
    def test_construct_params(self):
        msg = AnymailInboundMessage.construct(
            from_email="from@example.com",
            to="to@example.com",
            cc="cc@example.com",
            subject="test subject",
        )
        self.assertEqual(msg["From"], "from@example.com")
        self.assertEqual(msg["To"], "to@example.com")
        self.assertEqual(msg["Cc"], "cc@example.com")
        self.assertEqual(msg["Subject"], "test subject")

        # ensures email.message.Message.__init__ ran:
        self.assertEqual(msg.defects, [])
        # ensures AnymailInboundMessage.__init__ ran:
        self.assertIsNone(msg.envelope_recipient)

    def test_construct_headers_from_mapping(self):
        msg = AnymailInboundMessage.construct(
            headers={"Reply-To": "reply@example.com", "X-Test": "anything"}
        )
        # headers are case-insensitive:
        self.assertEqual(msg["reply-to"], "reply@example.com")
        self.assertEqual(msg["X-TEST"], "anything")

    def test_construct_headers_from_pairs(self):
        # allows multiple instances of a header
        msg = AnymailInboundMessage.construct(
            headers=[
                ["Reply-To", "reply@example.com"],
                [
                    "Received",
                    "by 10.1.1.4 with SMTP id q4csp;"
                    " Sun, 22 Oct 2017 00:23:22 -0700 (PDT)",
                ],
                [
                    "Received",
                    "from mail.example.com (mail.example.com. [10.10.1.9])"
                    " by mx.example.com with SMTPS id 93s8iok for <to@example.com>;"
                    " Sun, 22 Oct 2017 00:23:21 -0700 (PDT)",
                ],
            ]
        )
        self.assertEqual(msg["Reply-To"], "reply@example.com")
        self.assertEqual(
            msg.get_all("Received"),
            [
                "by 10.1.1.4 with SMTP id q4csp; Sun, 22 Oct 2017 00:23:22 -0700 (PDT)",
                "from mail.example.com (mail.example.com. [10.10.1.9])"
                " by mx.example.com with SMTPS id 93s8iok for <to@example.com>;"
                " Sun, 22 Oct 2017 00:23:21 -0700 (PDT)",
            ],
        )

    def test_construct_headers_from_raw(self):
        # (note header "folding" in second Received header)
        msg = AnymailInboundMessage.construct(
            raw_headers=dedent(
                """\
                Reply-To: reply@example.com
                Subject: raw subject
                Content-Type: x-custom/custom
                Received: by 10.1.1.4 with SMTP id q4csp; Sun, 22 Oct 2017 00:23:22 -0700 (PDT)
                Received: from mail.example.com (mail.example.com. [10.10.1.9])
                 by mx.example.com with SMTPS id 93s8iok for <to@example.com>;
                 Sun, 22 Oct 2017 00:23:21 -0700 (PDT)
                """  # NOQA: E501
            ),
            subject="Explicit subject overrides raw",
        )
        self.assertEqual(msg["Reply-To"], "reply@example.com")
        self.assertEqual(
            msg.get_all("Received"),
            [
                # unfolding should have stripped newlines
                "by 10.1.1.4 with SMTP id q4csp; Sun, 22 Oct 2017 00:23:22 -0700 (PDT)",
                "from mail.example.com (mail.example.com. [10.10.1.9])"
                " by mx.example.com with SMTPS id 93s8iok for <to@example.com>;"
                " Sun, 22 Oct 2017 00:23:21 -0700 (PDT)",
            ],
        )
        self.assertEqual(msg.get_all("Subject"), ["Explicit subject overrides raw"])
        # Content-Type in raw header ignored:
        self.assertEqual(msg.get_all("Content-Type"), ["multipart/mixed"])

    def test_construct_bodies(self):
        # this verifies we construct the expected MIME structure;
        # see the `text` and `html` props (in the ConveniencePropTests below)
        # for an easier way to get to these fields (that works however constructed)
        msg = AnymailInboundMessage.construct(text="Plaintext body", html="HTML body")
        self.assertEqual(msg["Content-Type"], "multipart/mixed")
        self.assertEqual(len(msg.get_payload()), 1)

        related = msg.get_payload(0)
        self.assertEqual(related["Content-Type"], "multipart/related")
        self.assertEqual(len(related.get_payload()), 1)

        alternative = related.get_payload(0)
        self.assertEqual(alternative["Content-Type"], "multipart/alternative")
        self.assertEqual(len(alternative.get_payload()), 2)

        plaintext = alternative.get_payload(0)
        self.assertEqual(plaintext["Content-Type"], 'text/plain; charset="utf-8"')
        self.assertEqual(plaintext.get_content_text(), "Plaintext body")

        html = alternative.get_payload(1)
        self.assertEqual(html["Content-Type"], 'text/html; charset="utf-8"')
        self.assertEqual(html.get_content_text(), "HTML body")

    def test_construct_attachments(self):
        att1 = AnymailInboundMessage.construct_attachment(
            "text/csv",
            "One,Two\n1,2".encode("iso-8859-1"),
            charset="iso-8859-1",
            filename="test.csv",
        )

        att2 = AnymailInboundMessage.construct_attachment(
            "image/png",
            SAMPLE_IMAGE_CONTENT,
            filename=SAMPLE_IMAGE_FILENAME,
            content_id="abc123",
        )

        msg = AnymailInboundMessage.construct(attachments=[att1, att2])
        self.assertEqual(msg["Content-Type"], "multipart/mixed")
        self.assertEqual(len(msg.get_payload()), 2)  # bodies (related), att1

        att1_part = msg.get_payload(1)
        self.assertEqual(
            att1_part["Content-Type"], 'text/csv; name="test.csv"; charset="iso-8859-1"'
        )
        self.assertEqual(
            att1_part["Content-Disposition"], 'attachment; filename="test.csv"'
        )
        self.assertNotIn("Content-ID", att1_part)
        self.assertEqual(att1_part.get_content_text(), "One,Two\n1,2")

        related = msg.get_payload(0)
        # alternatives (with no bodies in this test); att2:
        self.assertEqual(len(related.get_payload()), 2)
        att2_part = related.get_payload(1)
        self.assertEqual(
            att2_part["Content-Type"], 'image/png; name="sample_image.png"'
        )
        self.assertEqual(
            att2_part["Content-Disposition"], 'inline; filename="sample_image.png"'
        )
        self.assertEqual(att2_part["Content-ID"], "<abc123>")
        self.assertEqual(att2_part.get_content_bytes(), SAMPLE_IMAGE_CONTENT)

    def test_construct_attachments_from_uploaded_files(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        file = SimpleUploadedFile(
            SAMPLE_IMAGE_FILENAME, SAMPLE_IMAGE_CONTENT, "image/png"
        )
        att = AnymailInboundMessage.construct_attachment_from_uploaded_file(
            file, content_id="abc123"
        )
        self.assertEqual(att["Content-Type"], 'image/png; name="sample_image.png"')
        self.assertEqual(
            att["Content-Disposition"], 'inline; filename="sample_image.png"'
        )
        self.assertEqual(att["Content-ID"], "<abc123>")
        self.assertEqual(att.get_content_bytes(), SAMPLE_IMAGE_CONTENT)

    def test_construct_attachments_from_base64_data(self):
        # This is a fairly common way for ESPs to provide attachment content to webhooks
        content = b64encode(SAMPLE_IMAGE_CONTENT)
        att = AnymailInboundMessage.construct_attachment(
            content_type="image/png", content=content, base64=True
        )
        self.assertEqual(att.get_content_bytes(), SAMPLE_IMAGE_CONTENT)

    def test_construct_attachment_unicode_filename(self):
        # Issue #197
        att = AnymailInboundMessage.construct_attachment(
            content_type="text/plain",
            content="Unicode ✓",
            charset="utf-8",
            base64=False,
            filename="Simulácia.txt",
            content_id="inline-id",
        )
        self.assertEqual(att.get_filename(), "Simulácia.txt")
        self.assertTrue(att.is_inline_attachment())
        self.assertEqual(att.get_content_text(), "Unicode ✓")

    def test_parse_raw_mime(self):
        # (we're not trying to exhaustively test email.parser MIME handling here;
        # just that AnymailInboundMessage.parse_raw_mime calls it correctly)
        raw = dedent(
            """\
            Content-Type: text/plain
            Subject: This is a test message

            This is a test body.
            """
        )
        msg = AnymailInboundMessage.parse_raw_mime(raw)
        self.assertEqual(msg["Subject"], "This is a test message")
        self.assertEqual(msg.get_content_text(), "This is a test body.\n")
        self.assertEqual(msg.defects, [])

    # (see test_attachment_as_uploaded_file below
    # for parsing basic attachment from raw mime)

    def test_parse_raw_mime_bytes(self):
        raw = (
            b"Content-Type: text/plain; charset=ISO-8859-3\r\n"
            b"Content-Transfer-Encoding: 8bit\r\n"
            b"Subject: Test bytes\r\n"
            b"\r\n"
            b"\xD8i estas retpo\xFEto.\r\n"
        )
        msg = AnymailInboundMessage.parse_raw_mime_bytes(raw)
        self.assertEqual(msg["Subject"], "Test bytes")
        self.assertEqual(msg.get_content_text(), "Ĝi estas retpoŝto.\r\n")
        self.assertEqual(msg.get_content_bytes(), b"\xD8i estas retpo\xFEto.\r\n")
        self.assertEqual(msg.defects, [])

    def test_parse_raw_mime_8bit_utf8(self):
        # In come cases, the message below ends up with
        # 'Content-Transfer-Encoding: 8bit', so needs to be parsed as bytes, not text
        # (see https://bugs.python.org/issue18271).
        # Message.as_string() returns str (text), not bytes.
        # (This might be a Django bug; plain old MIMEText avoids the problem by using
        # 'Content-Transfer-Encoding: base64', which parses fine as text or bytes.)
        # Either way, AnymailInboundMessage should try to sidestep the whole issue.
        raw = SafeMIMEText("Unicode ✓", "plain", "utf-8").as_string()
        msg = AnymailInboundMessage.parse_raw_mime(raw)
        self.assertEqual(msg.text, "Unicode ✓")  # *not* "Unicode \\u2713"

    def test_parse_raw_mime_file_text(self):
        with open(sample_email_path(), mode="r") as fp:
            msg = AnymailInboundMessage.parse_raw_mime_file(fp)
        self.assertEqual(msg["Subject"], "Test email")
        self.assertEqual(msg.text, "Hi Bob, This is a message. Thanks!\n")
        self.assertEqual(
            msg.get_all("Received"),
            [  # this is the first line in the sample email file
                "by luna.mailgun.net with SMTP mgrt 8734663311733;"
                " Fri, 03 May 2013 18:26:27 +0000"
            ],
        )

    def test_parse_raw_mime_file_bytes(self):
        with open(sample_email_path(), mode="rb") as fp:
            msg = AnymailInboundMessage.parse_raw_mime_file(fp)
        self.assertEqual(msg["Subject"], "Test email")
        self.assertEqual(msg.text, "Hi Bob, This is a message. Thanks!\n")
        self.assertEqual(
            msg.get_all("Received"),
            [  # this is the first line in the sample email file
                "by luna.mailgun.net with SMTP mgrt 8734663311733;"
                " Fri, 03 May 2013 18:26:27 +0000"
            ],
        )


class AnymailInboundMessageConveniencePropTests(SimpleTestCase):
    # AnymailInboundMessage defines several properties to simplify reading
    # commonly-used items in an email.message.Message

    def test_address_props(self):
        msg = AnymailInboundMessage.construct(
            from_email='"Sender, Inc." <sender@example.com>',
            to="First To <to1@example.com>, to2@example.com",
            cc="First Cc <cc1@example.com>, cc2@example.com",
        )
        self.assertEqual(str(msg.from_email), '"Sender, Inc." <sender@example.com>')
        self.assertEqual(msg.from_email.addr_spec, "sender@example.com")
        self.assertEqual(msg.from_email.display_name, "Sender, Inc.")
        self.assertEqual(msg.from_email.username, "sender")
        self.assertEqual(msg.from_email.domain, "example.com")

        self.assertEqual(len(msg.to), 2)
        self.assertEqual(msg.to[0].addr_spec, "to1@example.com")
        self.assertEqual(msg.to[0].display_name, "First To")
        self.assertEqual(msg.to[1].addr_spec, "to2@example.com")
        self.assertEqual(msg.to[1].display_name, "")

        self.assertEqual(len(msg.cc), 2)
        self.assertEqual(msg.cc[0].address, "First Cc <cc1@example.com>")
        self.assertEqual(msg.cc[1].address, "cc2@example.com")

        # Default None/empty lists
        msg = AnymailInboundMessage()
        self.assertIsNone(msg.from_email)
        self.assertEqual(msg.to, [])
        self.assertEqual(msg.cc, [])

    def test_body_props(self):
        msg = AnymailInboundMessage.construct(text="Test plaintext", html="Test HTML")
        self.assertEqual(msg.text, "Test plaintext")
        self.assertEqual(msg.html, "Test HTML")

        # Make sure attachments don't confuse it
        att_text = AnymailInboundMessage.construct_attachment(
            "text/plain", "text attachment"
        )
        att_html = AnymailInboundMessage.construct_attachment(
            "text/html", "html attachment"
        )

        msg = AnymailInboundMessage.construct(
            text="Test plaintext", attachments=[att_text, att_html]
        )
        self.assertEqual(msg.text, "Test plaintext")
        self.assertIsNone(msg.html)  # no html body (the html attachment doesn't count)

        msg = AnymailInboundMessage.construct(
            html="Test HTML", attachments=[att_text, att_html]
        )
        # no plaintext body (the text attachment doesn't count):
        self.assertIsNone(msg.text)
        self.assertEqual(msg.html, "Test HTML")

        # Default None
        msg = AnymailInboundMessage()
        self.assertIsNone(msg.text)
        self.assertIsNone(msg.html)

    def test_body_props_charsets(self):
        text_8859_10 = "Detta är det vanliga innehållet".encode("ISO-8859-10")
        html_8859_8 = "<p>HTML זהו תוכן</p>".encode("ISO-8859-8")
        raw = dedent(
            """\
            MIME-Version: 1.0
            Subject: Charset test
            Content-Type: multipart/alternative; boundary="this_is_a_boundary"

            --this_is_a_boundary
            Content-Type: text/plain; charset=ISO-8859-10
            Content-Transfer-Encoding: QUOTED-PRINTABLE

            {text}
            --this_is_a_boundary
            Content-Type: text/html; charset=ISO-8859-8
            Content-Transfer-Encoding: QUOTED-PRINTABLE

            {html}
            --this_is_a_boundary--
            """
        ).format(
            text=quopri.encodestring(text_8859_10).decode("ASCII"),
            html=quopri.encodestring(html_8859_8).decode("ASCII"),
        )

        msg = AnymailInboundMessage.parse_raw_mime(raw)
        self.assertEqual(msg.defects, [])
        self.assertEqual(msg.text, "Detta är det vanliga innehållet")
        self.assertEqual(msg.html, "<p>HTML זהו תוכן</p>")

        self.assertEqual(msg.get_payload(0).get_content_bytes(), text_8859_10)
        self.assertEqual(
            msg.get_payload(0).get_content_text(), "Detta är det vanliga innehållet"
        )
        self.assertEqual(msg.get_payload(1).get_content_bytes(), html_8859_8)
        self.assertEqual(msg.get_payload(1).get_content_text(), "<p>HTML זהו תוכן</p>")

    def test_missing_or_invalid_charsets(self):
        """
        get_content_text has options for handling missing/invalid charset declarations
        """
        raw = dedent(
            """\
            Subject: Oops, missing charset declaration
            Content-Type: text/plain
            Content-Transfer-Encoding: quoted-printable

            Algunos programas de correo electr=f3nico est=e1n rotos
            """
        )
        msg = AnymailInboundMessage.parse_raw_mime(raw)
        self.assertEqual(msg.defects, [])

        # default is charset from Content-Type (or 'utf-8' if missing),
        # errors='replace'; .text uses defaults
        self.assertEqual(
            msg.get_content_text(),
            "Algunos programas de correo electr�nico est�n rotos\n",
        )
        self.assertEqual(
            msg.text, "Algunos programas de correo electr�nico est�n rotos\n"
        )

        # can give specific charset if you know headers are wrong/missing
        self.assertEqual(
            msg.get_content_text(charset="ISO-8859-1"),
            "Algunos programas de correo electrónico están rotos\n",
        )

        # can change error handling
        with self.assertRaises(UnicodeDecodeError):
            msg.get_content_text(errors="strict")
        self.assertEqual(
            msg.get_content_text(errors="ignore"),
            "Algunos programas de correo electrnico estn rotos\n",
        )

    def test_date_props(self):
        msg = AnymailInboundMessage.construct(
            headers={"Date": "Mon, 23 Oct 2017 17:50:55 -0700"}
        )
        self.assertEqual(msg.date.isoformat(), "2017-10-23T17:50:55-07:00")

        # Default None
        self.assertIsNone(AnymailInboundMessage().date)

    def test_attachments_prop(self):
        att = AnymailInboundMessage.construct_attachment(
            "image/png", SAMPLE_IMAGE_CONTENT, filename=SAMPLE_IMAGE_FILENAME
        )

        msg = AnymailInboundMessage.construct(attachments=[att])
        self.assertEqual(msg.attachments, [att])

        # Default empty list
        self.assertEqual(AnymailInboundMessage().attachments, [])

    def test_inline_attachments_prop(self):
        att = AnymailInboundMessage.construct_attachment(
            "image/png",
            SAMPLE_IMAGE_CONTENT,
            filename=SAMPLE_IMAGE_FILENAME,
            content_id="abc123",
        )

        msg = AnymailInboundMessage.construct(attachments=[att])
        self.assertEqual(msg.inline_attachments, {"abc123": att})

        # Default empty dict
        self.assertEqual(AnymailInboundMessage().inline_attachments, {})

    def test_attachment_as_uploaded_file(self):
        raw = dedent(
            """\
            MIME-Version: 1.0
            Subject: Attachment test
            Content-Type: multipart/mixed; boundary="this_is_a_boundary"

            --this_is_a_boundary
            Content-Type: text/plain; charset="UTF-8"

            The test sample image is attached below.

            --this_is_a_boundary
            Content-Type: image/png; name="sample_image.png"
            Content-Disposition: attachment; filename="sample_image.png"
            Content-Transfer-Encoding: base64

            iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAABHNCSVQICAgIfAhkiAAAAAlwSFlz
            AAALEgAACxIB0t1+/AAAABR0RVh0Q3JlYXRpb24gVGltZQAzLzEvMTNoZNRjAAAAHHRFWHRTb2Z0
            d2FyZQBBZG9iZSBGaXJld29ya3MgQ1M1cbXjNgAAAZ1JREFUWIXtl7FKA0EQhr+TgIFgo5BXyBUp
            fIGksLawUNAXWFFfwCJgBAtfIJFMLXgQn8BSwdpCiPcKAdOIoI2x2Dmyd7kYwXhp9odluX/uZv6d
            nZu7DXowxiKZi0IAUHKCvxcsoAIEpST4IawVGb0Hb0BlpcigefACvAAvwAsoTTGGlwwzBAyivLUP
            EZrOM10AhGOH2wWugVVlHoAdhJHrPC8DNR0JGsAAQ9mxNzBOMNjS4Qrq69U5EKmf12ywWVsQI4QI
            IbCn3Gnmnk7uk1bokfooI7QRDlQIGCdzPwiYh0idtXNs2zq3UqwVEiDcu/R0DVjUnFpItuPSscfA
            FXCGSfEAdZ2fVeQ68OjYWwi3ycVvMhABGwgfKXZScHeZ+4c6VzN8FbuYukvOykCs+z8PJ0xqIXYE
            d4ALoKlVH2IIgUHWwd/6gNAFPjPcCPvKNTDcYAj1lXzKc7GIRrSZI6yJzcQ+dtV9bD+IkHThBj34
            4j9/yYxupaQbXPJLNqsGFgeZ6qwpLP1b4AV4AV5AoKfjpR5OwR6VKwULCAC+AQV4W9Ps4uZQAAAA
            AElFTkSuQmCC
            --this_is_a_boundary--
            """
        )

        msg = AnymailInboundMessage.parse_raw_mime(raw)
        attachment = msg.attachments[0]
        attachment_file = attachment.as_uploaded_file()

        self.assertEqual(attachment_file.name, "sample_image.png")
        self.assertEqual(attachment_file.content_type, "image/png")
        self.assertEqual(attachment_file.read(), SAMPLE_IMAGE_CONTENT)

    def test_attachment_as_uploaded_file_security(self):
        # Raw attachment filenames can be malicious; we want to make sure that
        # our Django file converter sanitizes them (as much as any uploaded filename)
        raw = dedent(
            """\
            MIME-Version: 1.0
            Subject: Attachment test
            Content-Type: multipart/mixed; boundary="this_is_a_boundary"

            --this_is_a_boundary
            Content-Type: text/plain; charset="UTF-8"

            The malicious attachment filenames below need to get sanitized

            --this_is_a_boundary
            Content-Type: text/plain; name="report.txt"
            Content-Disposition: attachment; filename="/etc/passwd"

            # (not that overwriting /etc/passwd is actually a thing
            # anymore, but you get the point)
            --this_is_a_boundary
            Content-Type: text/html
            Content-Disposition: attachment; filename="../static/index.html"

            <body>Hey, did I overwrite your site?</body>
            --this_is_a_boundary--
            """
        )
        msg = AnymailInboundMessage.parse_raw_mime(raw)
        attachments = msg.attachments

        # you wouldn't want to actually write here:
        self.assertEqual(attachments[0].get_filename(), "/etc/passwd")
        # path removed - good!:
        self.assertEqual(attachments[0].as_uploaded_file().name, "passwd")

        # ditto for relative paths:
        self.assertEqual(attachments[1].get_filename(), "../static/index.html")
        self.assertEqual(attachments[1].as_uploaded_file().name, "index.html")


class AnymailInboundMessageAttachedMessageTests(SimpleTestCase):
    # message/rfc822 attachments should get parsed recursively

    original_raw_message = dedent(
        """\
        MIME-Version: 1.0
        From: sender@example.com
        Subject: Original message
        Return-Path: bounces@inbound.example.com
        Content-Type: multipart/related; boundary="boundary-orig"

        --boundary-orig
        Content-Type: text/html; charset="UTF-8"

        <img src="cid:abc123"> Here is your message!

        --boundary-orig
        Content-Type: image/png; name="sample_image.png"
        Content-Disposition: inline
        Content-ID: <abc123>
        Content-Transfer-Encoding: base64

        {image_content_base64}
        --boundary-orig--
        """
    ).format(image_content_base64=b64encode(SAMPLE_IMAGE_CONTENT).decode("ascii"))

    def test_parse_rfc822_attachment_from_raw_mime(self):
        # message/rfc822 attachments should be parsed recursively
        raw = dedent(
            """\
            MIME-Version: 1.0
            From: mailer-demon@example.org
            Subject: Undeliverable
            To: bounces@inbound.example.com
            Content-Type: multipart/mixed; boundary="boundary-bounce"

            --boundary-bounce
            Content-Type: text/plain

            Your message was undeliverable due to carrier pigeon strike.
            The original message is attached.

            --boundary-bounce
            Content-Type: message/rfc822
            Content-Disposition: attachment

            {original_raw_message}
            --boundary-bounce--
            """
        ).format(original_raw_message=self.original_raw_message)

        msg = AnymailInboundMessage.parse_raw_mime(raw)
        self.assertIsInstance(msg, AnymailInboundMessage)

        att = msg.get_payload(1)
        self.assertIsInstance(att, AnymailInboundMessage)
        self.assertEqual(att.get_content_type(), "message/rfc822")
        self.assertTrue(att.is_attachment())

        orig_msg = att.get_payload(0)
        self.assertIsInstance(orig_msg, AnymailInboundMessage)
        self.assertEqual(orig_msg["Subject"], "Original message")
        self.assertEqual(orig_msg.get_content_type(), "multipart/related")
        self.assertEqual(att.get_content_text(), self.original_raw_message)

        orig_inline_att = orig_msg.get_payload(1)
        self.assertEqual(orig_inline_att.get_content_type(), "image/png")
        self.assertTrue(orig_inline_att.is_inline_attachment())
        self.assertEqual(orig_inline_att.get_payload(decode=True), SAMPLE_IMAGE_CONTENT)

    def test_construct_rfc822_attachment_from_data(self):
        # constructed message/rfc822 attachment should end up as parsed message
        # (same as if attachment was parsed from raw mime, as in previous test)
        att = AnymailInboundMessage.construct_attachment(
            "message/rfc822", self.original_raw_message
        )
        self.assertIsInstance(att, AnymailInboundMessage)
        self.assertEqual(att.get_content_type(), "message/rfc822")
        self.assertTrue(att.is_attachment())
        self.assertEqual(att.get_content_text(), self.original_raw_message)

        orig_msg = att.get_payload(0)
        self.assertIsInstance(orig_msg, AnymailInboundMessage)
        self.assertEqual(orig_msg["Subject"], "Original message")
        self.assertEqual(orig_msg.get_content_type(), "multipart/related")


class EmailParserBehaviorTests(SimpleTestCase):
    # Python 3.5+'s EmailParser should handle all of these, so long as it's not
    # invoked with its default policy=compat32. This double checks we're using it
    # properly. (Also, older versions of Anymail included workarounds for these
    # in older, broken versions of the EmailParser.)

    def test_parse_folded_headers(self):
        raw = dedent(
            """\
            Content-Type: text/plain
            Subject: This subject uses
             header folding
            X-Json: {"problematic":
             ["encoded newline\\n",
             "comma,semi;no space"]}

            Not-A-Header: This is the body.
             It is not folded.
            """
        )
        for end in ("\n", "\r", "\r\n"):  # check NL, CR, and CRNL line-endings
            msg = AnymailInboundMessage.parse_raw_mime(raw.replace("\n", end))
            self.assertEqual(msg["Subject"], "This subject uses header folding")
            self.assertEqual(
                msg["X-Json"],
                '{"problematic": ["encoded newline\\n", "comma,semi;no space"]}',
            )
            self.assertEqual(
                msg.get_content_text(),
                "Not-A-Header: This is the body.{end} It is not folded.{end}".format(
                    end=end
                ),
            )
            self.assertEqual(msg.defects, [])

    def test_parse_encoded_headers(self):
        # RFC2047 header encoding
        raw = dedent(
            """\
            Content-Type: text/plain
            From: =?US-ASCII?Q?Keith_Moore?= <moore@example.com>
            To: =?ISO-8859-1?Q?Keld_J=F8rn_Simonsen?= <keld@example.com>,
             =?ISO-8859-1?Q?Andr=E9?= "Pirard, Jr." <PIRARD@example.com>
            Cc: =?utf-8?b?TmfGsOG7nWkgbmjhuq1u?= <cc@xn--th-e0a.example.com>
            Subject: =?ISO-8859-1?B?SWYgeW91IGNhbiByZWFkIHRoaXMgeW8=?=
             =?utf-8?q?u_understand_the_example=E2=9C=93?=
            X-Broken: =?utf-8?q?Not_a_char:_=88.?=

            Some examples adapted from http://dogmamix.com/MimeHeadersDecoder/
            """
        )
        msg = AnymailInboundMessage.parse_raw_mime(raw)

        self.assertEqual(msg["From"], "Keith Moore <moore@example.com>")
        self.assertEqual(msg.from_email.display_name, "Keith Moore")
        self.assertEqual(msg.from_email.addr_spec, "moore@example.com")

        self.assertEqual(
            msg["To"],
            "Keld Jørn Simonsen <keld@example.com>, "
            '"André Pirard, Jr." <PIRARD@example.com>',
        )
        self.assertEqual(msg.to[0].display_name, "Keld Jørn Simonsen")
        self.assertEqual(msg.to[1].display_name, "André Pirard, Jr.")

        # Note: Like email.headerregistry.Address, Anymail decodes an RFC2047-encoded
        # display_name, but does not decode a punycode domain.
        # (Use `idna.decode(domain)` if you need that.)
        self.assertEqual(msg["Cc"], "Người nhận <cc@xn--th-e0a.example.com>")
        self.assertEqual(msg.cc[0].display_name, "Người nhận")
        self.assertEqual(msg.cc[0].addr_spec, "cc@xn--th-e0a.example.com")
        self.assertEqual(msg.cc[0].domain, "xn--th-e0a.example.com")

        # Subject breaks between 'o' and 'u' in the word "you", must be re-joined
        # without space. Also tests joining encoded words with different charsets:
        self.assertEqual(
            msg["Subject"],
            "If you can read this you understand the example\N{CHECK MARK}",
        )

        # Replace illegal encodings (rather than causing error):
        self.assertEqual(msg["X-Broken"], "Not a char: \N{REPLACEMENT CHARACTER}.")

    def test_parse_encoded_params(self):
        raw = dedent(
            """\
            MIME-Version: 1.0
            Content-Type: multipart/mixed; boundary="this_is_a_boundary"

            --this_is_a_boundary
            Content-Type: text/plain; charset="UTF-8"

            This is the body

            --this_is_a_boundary
            Content-Type: text/plain; name*=us-ascii''TPS%20Report
            Content-Disposition: attachment;
             filename*=iso-8859-1''Une%20pi%E8ce%20jointe%2Etxt

            This is an attachment
            --this_is_a_boundary--
            """
        )
        msg = AnymailInboundMessage.parse_raw_mime(raw)
        att = msg.attachments[0]
        self.assertTrue(att.is_attachment())
        self.assertEqual(att.get_content_disposition(), "attachment")
        self.assertEqual(
            collapse_rfc2231_value(att.get_param("Name", header="Content-Type")),
            "TPS Report",
        )
        self.assertEqual(att.get_filename(), "Une pièce jointe.txt")
