# Adding a new ESP

Some developer notes on adding support for a new ESP.

Please refer to the comments in Anymail's code---most of the
extension points are (reasonably) well documented, and will
indicate what you need to implement and what Anymail provides
for you.

This document adds general background and covers some design
decisions that aren't necessarily obvious from the code.

## Getting started

- Don't want to do _all_ of this? **That's OK!** A partial PR
  is better than no PR. And opening a work-in-progress PR
  early is a really good idea.
- Don't want to do _any_ of this? Use GitHub issues to request
  support for other ESPs in Anymail.
- It's often easiest to copy and modify the existing code
  for an ESP with a similar API. There are some hints in each
  section below what might be "similar".

### Which ESPs?

Anymail is best suited to _transactional_ ESP APIs. The Django core
mail package it builds on isn't a good match for most _bulk_ mail APIs.
(If you can't specify an individual recipient email address and at
least some of the message content, it's probably not a transactional API.)

Similarly, Anymail is best suited to ESPs that offer some value-added
features beyond simply sending email. If you'd get exactly the same
results by pointing Django's built-in SMTP EmailBackend at the ESP's
SMTP endpoint, there's really no need to add it to Anymail.

We strongly prefer ESPs where we'll be able to run live integration
tests regularly. That requires the ESP have a free tier (testing is
extremely low volume), a sandbox API, or that they offer developer
accounts for open source projects like Anymail.

## EmailBackend and payload

Anymail abstracts a lot of common functionality into its base classes;
your code should be able to focus on the ESP-specific parts.

You'll subclass a backend and a payload for your ESP implementation:

- Backend (subclass `AnymailBaseBackend` or `AnymailRequestsBackend`):
  implements Django's email API, orchestrates the overall sending process
  for multiple messages.

- Payload (subclass `BasePayload` or `RequestsPayload`)
  implements conversion of a single Django `EmailMessage` to parameters
  for the ESP API.

Whether you start from the base or requests version depends on whether
you'll be using an ESP client library or calling their HTTP API directly.

### Client lib or HTTP API?

Which to pick? It's a bit of a judgement call:

- Often, ESP Python client libraries don't seem to be actively maintained.
  Definitely avoid those.

- Some client libraries are just thin wrappers around Requests (or urllib).
  There's little value in using those, and you'll lose some optimizations
  built into `AnymailRequestsBackend`.

- Surprisingly often, client libraries (unintentionally) impose limitations
  that are more restrictive than than (or conflict with) the underlying ESP API.
  You should report those bugs against the library. (Or if they were already
  reported a long time ago, see the first point above.)

- Some ESP APIs have really complex (or obscure) payload formats,
  or authorization schemes that are non-trivial to implement in Requests.
  If the client library handles this for you, it's a better choice.

When in doubt, it's usually fine to use `AnymailRequestsBackend` and write
directly to the HTTP API.

### Requests backend (using HTTP API)

Good staring points for similar ESP APIs:

- JSON payload: Postmark
- Form-encoded payload: Mailgun

Different API endpoints for (e.g.,) template vs. regular send?
Implement `get_api_endpoint()` in your Payload.

Need to encode JSON in the payload? Use `self.serialize_json()`
(it has some extra error handling).

Need to parse JSON in the API response? Use `self.deserialize_json_response()`
(same reason).

### Base backend (using client lib)

Good starting points: Test backend; SparkPost

Don't forget to add an entry for your ESP in pyproject.toml in the
`[project.optional-dependencies]` section.

If the client lib supports the notion of a reusable API "connection"
(or session), you should override `open()` and `close()` to provide
API state caching. See the notes in the base implementation.
(The RequestsBackend implements this using Requests sessions.)

### Payloads

Look for the "Abstract implementation" comment in `base.BasePayload`.
Your payload should consider implementing everything below there.

#### Email addresses

All payload methods dealing with email addresses (recipients, from, etc.) are
passed `anymail.utils.EmailAddress` objects, so you don't have to parse them.

`email.display_name` is the name, `email.addr_spec` is the email, and
`str(email)` is both fully formatted, with a properly-quoted display name.

For recipients, you can implement whichever of these Payload methods
is most convenient for the ESP API:

- `set_to(emails)`, `set_cc(emails)`, and `set_bcc(emails)`
- `set_recipients(type, emails)`
- `add_recipient(type, email)`

#### Attachments

The payload `set_attachments()`/`add_attachment()` methods are passed
`anymail.utils.Attachment` objects, which are normalized so you don't have
to handle the variety of formats Django allows. All have `name`, `content`
(as a bytestream) and `mimetype` properties.

Use `att.inline` to determine if the attachment is meant to be inline.
(Don't just check for content-id.) If so, `att.content_id` is the Content-ID
with angle brackets, and `att.cid` is without angle brackets.

Use `att.base64content` if your ESP wants base64-encoded data.

#### AnymailUnsupportedFeature and validating parameters

Should your payload use `self.unsupported_feature()`? The rule of thumb is:

- If it _cannot be accurately communicated_ to the ESP API, that's unsupported.
  E.g., the user provided multiple `tags` but the ESP's "Tag" parameter only accepts
  a (single) string value.

- Anymail avoids enforcing ESP policies (because these tend to change over time, and
  we don't want to update our code). So if it _can_ be accurately communicated to the
  ESP API, that's _not_ unsupported---even if the ESP docs say it's not allowed.
  E.g., the user provided 10 `tags`, the ESP's "Tags" parameter accepts a list,
  but is documented maximum 3 tags. Anymail should pass the list of 10 tags,
  and let the ESP error if it chooses.

Similarly, Anymail doesn't enforce allowed attachment types, maximum attachment size,
maximum number of recipients, etc. That's the ESP's responsibility.

One exception: if the ESP mis-handles certain input (e.g., drops the message but
returns "success"; mangles email display names), and seems unlikely to fix the problem,
we'll typically add a warning or workaround to Anymail.
(As well as reporting the problem to the ESP.)

#### Batch send and splitting `to`

One of the more complicated Payload functions is handling multiple `to` addresses
properly.

If the user has set `merge_data`, a separate message should get sent to each `to`
address, and recipients should not see the full To list. If `merge_data` is not set,
a single message should be sent with all addresses in the To header.

Most backends handle this in the Payload's `serialize_data` method, by restructuring
the payload if `merge_data` is not None.

#### Tests

Every backend needs mock tests, that use a mocked API to verify the ESP is being called
correctly. It's often easiest to copy and modify the backend tests for an ESP with
a similar API.

Ideally, every backend should also have live integration tests, because sometimes the
docs don't quite match the real world. (And because ESPs have been known to change APIs
without notice.) Anymail's CI runs the live integration tests at least weekly.

## Webhooks

ESP webhook documentation is _almost always_ vague on at least some aspects of the
webhook event data, and example payloads in their docs are often outdated (and/or
manually constructed and inaccurate).

Runscope (or similar) is an extremely useful tool for collecting actual webhook
payloads.

### Tracking webhooks

Good starting points:

- JSON event payload: SendGrid, Postmark
- Form data event payload: Mailgun

(more to come)

### Inbound webhooks

Raw MIME vs. ESP-parsed fields? If you're given both, the raw MIME is usually easier
to work with.

(more to come)

## Project goals

Anymail aims to:

- Normalize common transactional ESP functionality (to simplify
  switching between ESPs)

- But allow access to the full ESP feature set, through
  `esp_extra` (so Anymail doesn't force users into
  least-common-denominator functionality, or prevent use of
  newly-released ESP features)

- Present a Pythonic, Djangotic API, and play well with Django
  and other Django reusable apps

- Maintain compatibility with all currently supported Django versions---and
  even unsupported minor versions in between (so Anymail isn't the package
  that forces you to upgrade Django---or that prevents you from upgrading
  when you're ready)

Many of these goals incorporate lessons learned from Anymail's predecessor
Djrill project. And they mean that django-anymail is biased toward implementing
_relatively_ thin wrappers over ESP transactional sending, tracking, and receiving APIs.
Anything that would add Django models to Anymail is probably out of scope.
(But could be a great companion package.)
