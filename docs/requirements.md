# notify_kit — Requirements

This document is the testable specification for notify_kit, a standalone
Python package that sends messages over pluggable channels (email, SMS,
WhatsApp, push) from stored templates and structured facts. It is written
as plain-English rules and avoids naming modules, classes or functions, so
the API can take whatever shape building it shows is right without
invalidating the rules. Each rule's test names it with
`@pytest.mark.requirement("Rn")`, and a coverage test checks that every
rule marked [✅] or [X] has one.

Convention:

- **[✅]** — positive ability is wired and covered by tests.
- **[X]** — prohibition is enforced and covered by tests.
- **[GAP]** — agreed, not yet implemented; cites the issue that adds it.
- **[UNTESTED]** — implemented, but no test proves it yet.

Every rule below is **[GAP]** until #1 implements it.

## Vocabulary

- The **caller** is the application using notify_kit. It decides who is
  messaged, on which channel and when; notify_kit does none of that.
- A **channel kind** is a way to deliver: `email`, `sms`, `whatsapp` or
  `push`.
- A **provider** is one service that delivers a channel kind (Resend and
  Brevo for email, for example), registered under a name.
- A **recipient** is one person to send to: an address for the channel
  kind (an email address, a phone number in international form, a push
  token), with an optional display name and an optional language.
- A **template** is the stored form of one message for one channel kind,
  identified by a **key** chosen by the caller.
- **Facts** are a flat mapping of names to plain values (text, numbers,
  booleans, dates) that fill a template's placeholders. Facts are data,
  never markup.
- A **layout** is the frame around every email (header, logo, footer),
  supplied by the caller as data.
- A **send** is one request to deliver one template, with one set of facts,
  to a list of recipients through one provider.
- A **result** is the outcome of a send for one recipient: `sent`,
  `failed` or `skipped`, with a reason.

---

## Independence

- **R1** [GAP] (#1) notify_kit has no knowledge of its caller's domain: it
  has no notion of users, accounts, roles, preferences, categories or
  gates, and takes none as input.
- **R2** [GAP] (#1) notify_kit reads no configuration from the environment,
  files or a database of its own: provider credentials, sender identities,
  templates and layouts are all handed in by the caller.
- **R3** [GAP] (#1) notify_kit opens no network connection except through a
  provider during a send.
- **R4** [GAP] (#1) The package installs and its tests pass with no network
  access and no external service configured.

## Providers

- **R5** [GAP] (#1) A caller can register a provider for a channel kind
  under a name, handing in its credentials and its sender identity (for
  email: the from-address and display name).
- **R6** [GAP] (#1) Several providers can be registered for the same
  channel kind at once (two email providers, for example), and each send
  names the one to use.
- **R7** [GAP] (#1) The sender identity belongs to the registration, not to
  the provider type: two registrations of the same provider can send from
  different addresses.
- **R8** [X] (#1) Registering a provider without the credentials or sender
  identity it needs fails at registration, naming what is missing, rather
  than at the first send.
- **R9** [X] (#1) A send naming a provider that is not registered, or one
  registered for a different channel kind, fails before anything is sent.
- **R10** [GAP] (#1) A console provider for email writes each message it
  would send to a log instead of sending it, needs no credentials, and is
  what development and tests use.
- **R11** [GAP] (#1) Email can be sent through Resend and through Brevo.
- **R12** [GAP] (#1) A fake provider exists for every channel kind: it
  records each message it is given, can be told to fail for chosen
  recipients, and is what tests use to assert what would have been sent.
- **R13** [X] (#1) A provider's credentials never appear in a result, an
  error, a log line or the text of an exception.

## Templates

- **R14** [GAP] (#1) Templates are kept in a template store the caller
  chooses. notify_kit defines what a store must do and ships an in-memory
  store; a persistent store is the caller's.
- **R15** [GAP] (#1) A caller can create, read, list, update and delete
  templates through the store.
- **R16** [GAP] (#1) A template is identified by its key, its channel kind
  and its language; one key can have one template per channel kind and per
  language.
- **R17** [X] (#1) Creating a template whose key, channel kind and
  language already exist fails; updating or deleting one that does not
  exist fails.
- **R18** [GAP] (#1) Every template declares the facts it uses. Saving a
  template whose body uses a placeholder it does not declare fails, naming
  the placeholder.
- **R19** [GAP] (#1) An email template has a subject and a body. The body
  is markdown with placeholders; the subject is plain text with
  placeholders.
- **R20** [GAP] (#1) An SMS or WhatsApp template does not hold free text:
  it holds the provider's approved template identifier and the order in
  which declared facts fill the approved template's blanks.
- **R21** [GAP] (#1) A push template has a title and a short body, plain
  text with placeholders.

## Rendering

- **R22** [GAP] (#1) An email is rendered by filling the subject and body
  with the facts, converting the body from markdown to HTML, placing it in
  the layout, and producing a plain-text version alongside the HTML.
- **R23** [X] (#1) A fact's value is always inserted as literal text: a fact
  containing markdown, HTML, a link or an image reference renders as those
  characters, never as markup.
- **R24** [GAP] (#1) The layout (club or product name, logo URL, footer
  text) is supplied with the send or the provider registration, not stored
  in notify_kit; an absent logo renders a text-only header, never a broken
  image.
- **R25** [X] (#1) Rendering with a declared fact missing fails for that
  recipient with the missing fact named; nothing is sent to them.
- **R26** [GAP] (#1) Facts that are given but not declared by the template
  are ignored.
- **R27** [GAP] (#1) The template for a recipient is chosen by their
  language; when there is none in that language, a default language set by
  the caller is used.
- **R28** [GAP] (#1) A caller can render a template with facts without
  sending it, to preview exactly what a recipient would receive.

## Sending

- **R29** [GAP] (#1) A send takes the recipients, the template key, the
  facts and the provider to use, and returns one result per recipient, in
  the order given.
- **R30** [GAP] (#1) Sending is asynchronous: a caller can await it without
  blocking its event loop.
- **R31** [GAP] (#1) A recipient whose address does not suit the channel
  kind (an email address that is not one, a phone number not in
  international form) is `skipped` with that reason; the others are still
  sent.
- **R32** [GAP] (#1) A provider failure for one recipient makes that
  recipient's result `failed` with the provider's reason; it does not stop
  the send for the others and does not raise.
- **R33** [GAP] (#1) A result says which provider was used and carries the
  provider's message identifier when the provider returns one.
- **R34** [X] (#1) The same recipient listed twice in one send receives
  the message once; the second entry is `skipped` as a duplicate.
- **R35** [X] (#1) An empty recipient list sends nothing and returns no
  results.
- **R36** [GAP] (#1) notify_kit does not retry: a `failed` result is
  final for that send, and retrying is the caller's decision.
- **R37** [GAP] (#1) notify_kit keeps no record of what it sent: the
  results are returned to the caller, who records them as it chooses.

## Command line

- **R38** [GAP] (#1) A command sends one template, with facts given on the
  command line, to one address, through a named provider whose credentials
  are given on the command line or read from a file the command names.
- **R39** [GAP] (#1) The command can render without sending, printing the
  subject, the HTML and the plain text.

## Later channels

Recorded so the rules above are read in their light; each becomes rules
when its issue is filed.

- **SMS** — a provider for India, with a registered sender identifier and
  DLT-registered templates (R20).
- **WhatsApp** — a provider for Meta-approved templates (R20), through the
  Cloud API or a business solution provider.
- **Push** — Web Push for browsers and Firebase for Android apps (R21).
