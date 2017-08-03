.. _django-templates:

Using Django templates for email
================================

ESP's templating languages and merge capabilities are generally not compatible
with each other, which can make it hard to move email templates between them.

But since you're working in Django, you already have access to the
extremely-full-featured :mod:`Django templating system <django.template>`.
You don't even have to use Django's template syntax: it supports other
template languages (like Jinja2).

You're probably already using Django's templating system for your HTML pages,
so it can be an easy decision to use it for your email, too.

To compose email using *Django* templates, you can use Django's
:func:`~django.template.loaders.django.template.loader.render_to_string`
template shortcut to build the body and html.

Example that builds an email from the templates ``message_subject.txt``,
``message_body.txt`` and ``message_body.html``:

.. code-block:: python

    from django.core.mail import EmailMultiAlternatives
    from django.template import Context
    from django.template.loader import render_to_string

    merge_data = {
        'ORDERNO': "12345", 'TRACKINGNO': "1Z987"
    }

    plaintext_context = Context(autoescape=False)  # HTML escaping not appropriate in plaintext
    subject = render_to_string("message_subject.txt", merge_data, plaintext_context)
    text_body = render_to_string("message_body.txt", merge_data, plaintext_context)
    html_body = render_to_string("message_body.html", merge_data)

    msg = EmailMultiAlternatives(subject=subject, from_email="store@example.com",
                                 to=["customer@example.com"], body=text_body)
    msg.attach_alternative(html_body, "text/html")
    msg.send()


Helpful add-ons
---------------

These (third-party) packages can be helpful for building your email
in Django:

.. TODO: flesh this out

* django-templated-mail, django-mail-templated, django-mail-templated-simple
* Premailer, for inlining css
* BeautifulSoup, lxml, or html2text, for auto-generating plaintext from your html
