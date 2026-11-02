import json

import httpx
import pytest
from app.providers.brevo import BrevoProvider
from app.providers.fake_sms import FakeSmsProvider
from app.providers.resend import ResendProvider
from app.schemas.email_settings import EmailSettings

from notify_kit import ErrorCode, ProviderError, ProviderState, Recipient, Template


@pytest.fixture(params=[ResendProvider, BrevoProvider], ids=["resend", "brevo"])
def email_provider(request):
    return request.param(
        EmailSettings(
            api_key="secret-test-key",
            from_email="sender@example.com",
            from_name="Example",
        )
    )


def mock_transport(monkeypatch, handler):
    original = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: original(transport=transport, **kwargs)
    )


@pytest.mark.requirement("R19")
async def test_should_send_vendor_payload_with_stable_id_and_personalized_content(
    email_provider, monkeypatch
):
    recipient = Recipient("alice", "Alice", "alice@example.com")
    prepared = await email_provider.prepare(
        template=Template(
            "receipt",
            {
                "subject": "Hi $name",
                "text": "Amount $amount",
                "html": "<p>$name: $amount</p>",
            },
        ),
        metadata=None,
        recipient=recipient,
        facts={"amount": 42},
    )
    captured = []

    def handler(request):
        captured.append(request)
        return httpx.Response(201, json={"id": "remote", "messageId": "remote"})

    mock_transport(monkeypatch, handler)
    result = await email_provider.send(
        recipient=recipient, prepared=prepared, idempotency_key="delivery-1"
    )
    assert result.status == ProviderState.ACCEPTED
    assert result.message_id == "remote"
    request = captured[0]
    payload = json.loads(request.content)
    assert payload["subject"] == "Hi Alice"
    if isinstance(email_provider, ResendProvider):
        assert payload["text"] == "Amount 42"
        assert request.headers["Idempotency-Key"] == "delivery-1"
        assert request.headers["authorization"] == "Bearer secret-test-key"
    else:
        assert payload["htmlContent"] == "<p>Alice: 42</p>"
        assert payload["headers"]["idempotencyKey"] == "delivery-1"
        assert request.headers["api-key"] == "secret-test-key"
    assert "secret-test-key" not in json.dumps(prepared)


@pytest.mark.requirement("R23")
async def test_should_escape_html_facts_without_interpreting_markup(email_provider):
    prepared = await email_provider.prepare(
        template=Template(
            "literal", {"subject": "$value", "text": "$value", "html": "<p>$value</p>"}
        ),
        metadata=None,
        recipient=Recipient("alice", email="alice@example.com"),
        facts={
            "value": '<img src=x onerror="bad"> **markdown** [link](https://example.com)'
        },
    )
    assert "<img" not in prepared["html"]
    assert "&lt;img" in prepared["html"]
    assert "**markdown**" in prepared["html"]
    assert prepared["text"].startswith("<img")


@pytest.mark.requirement("R24")
async def test_should_generate_safe_html_without_requiring_a_logo_or_layout(
    email_provider,
):
    prepared = await email_provider.prepare(
        template=Template("plain", {"subject": "Notice", "text": "$value"}),
        metadata=None,
        recipient=Recipient("alice", email="alice@example.com"),
        facts={"value": "<literal>"},
    )
    assert prepared["html"] == "<pre>&lt;literal&gt;</pre>"
    assert "<img" not in prepared["html"]


@pytest.mark.requirement("R25")
async def test_should_name_missing_fact_and_reject_subject_newline(email_provider):
    with pytest.raises(ProviderError, match="Missing fact: amount"):
        await email_provider.prepare(
            template=Template("missing", {"subject": "hello", "text": "$amount"}),
            metadata=None,
            recipient=Recipient("alice", email="alice@example.com"),
            facts={},
        )
    with pytest.raises(ProviderError, match="newlines"):
        await email_provider.prepare(
            template=Template("newline", {"subject": "$value", "text": "body"}),
            metadata=None,
            recipient=Recipient("alice", email="alice@example.com"),
            facts={"value": "hello\nInjected"},
        )


@pytest.mark.requirement("R26")
async def test_should_ignore_unused_facts(email_provider):
    prepared = await email_provider.prepare(
        template=Template("simple", {"subject": "hello", "text": "body"}),
        metadata=None,
        recipient=Recipient("alice", email="alice@example.com"),
        facts={"unused": "never included"},
    )
    assert "never included" not in json.dumps(prepared)


@pytest.mark.requirement("R18")
async def test_should_validate_definition_during_registration(email_provider):
    with pytest.raises(ProviderError):
        await email_provider.register_template(
            template=Template("bad", {"text": "missing subject"}),
            idempotency_key="register",
        )
    with pytest.raises(ProviderError, match="placeholder"):
        await email_provider.register_template(
            template=Template("bad", {"subject": "Hello", "text": "$!"}),
            idempotency_key="register",
        )


@pytest.mark.requirement("R13")
@pytest.mark.parametrize(
    "status,state",
    [
        (400, ProviderState.PERMANENT_FAILURE),
        (401, ProviderState.PERMANENT_FAILURE),
        (429, ProviderState.TEMPORARY_FAILURE),
        (500, ProviderState.UNKNOWN),
    ],
)
async def test_should_classify_safe_vendor_diagnostics(
    email_provider, monkeypatch, status, state
):
    mock_transport(
        monkeypatch,
        lambda request: httpx.Response(
            status,
            json={"message": "rejected secret-test-key", "code": "vendor_code"},
            headers={"retry-after": "5"},
        ),
    )
    prepared = await email_provider.prepare(
        template=Template("simple", {"subject": "hello", "text": "body"}),
        metadata=None,
        recipient=Recipient("alice", email="alice@example.com"),
        facts={},
    )
    result = await email_provider.send(
        recipient=Recipient("alice", email="alice@example.com"),
        prepared=prepared,
        idempotency_key="id",
    )
    assert result.status == state
    assert "secret-test-key" not in result.reason
    assert "vendor_code" in result.reason
    if status == 429:
        assert result.retry_after_seconds == 5


@pytest.mark.requirement("R36")
@pytest.mark.parametrize(
    "exception,state",
    [
        (httpx.ConnectError, ProviderState.TEMPORARY_FAILURE),
        (httpx.ReadTimeout, ProviderState.UNKNOWN),
    ],
)
async def test_should_not_blindly_retry_uncertain_transport_failures(
    email_provider, monkeypatch, exception, state
):
    def handler(request):
        raise exception("raw exception with secret-test-key", request=request)

    mock_transport(monkeypatch, handler)
    prepared = await email_provider.prepare(
        template=Template("simple", {"subject": "hello", "text": "body"}),
        metadata=None,
        recipient=Recipient("alice", email="alice@example.com"),
        facts={},
    )
    result = await email_provider.send(
        recipient=Recipient("alice", email="alice@example.com"),
        prepared=prepared,
        idempotency_key="id",
    )
    assert result.status == state
    assert "secret-test-key" not in result.reason


@pytest.mark.requirement("R7")
async def test_should_preserve_per_instance_sender_identity():
    first = ResendProvider(
        EmailSettings(api_key="first-key", from_email="first@example.com")
    )
    second = ResendProvider(
        EmailSettings(api_key="second-key", from_email="second@example.com")
    )
    definition = Template("hello", {"subject": "Hello", "text": "body"})
    request = dict(
        template=definition,
        metadata=None,
        recipient=Recipient("alice", email="alice@example.com"),
        facts={},
    )
    assert (await first.prepare(**request))["from_email"] == "first@example.com"
    assert (await second.prepare(**request))["from_email"] == "second@example.com"
    assert first.headers("id")["Authorization"] != second.headers("id")["Authorization"]


@pytest.mark.requirement("R20")
async def test_should_require_fake_sms_registration_and_support_revision_lifecycle(
    caplog,
):
    provider = FakeSmsProvider()
    template = Template("sms", {"body": "Hello $name"})
    recipient = Recipient("alice", "Alice", phone="+919876543210")
    with pytest.raises(ProviderError) as error:
        await provider.prepare(
            template=template, metadata=None, recipient=recipient, facts={}
        )
    assert error.value.code == ErrorCode.TEMPLATE_NOT_REGISTERED
    metadata = await provider.register_template(
        template=template, idempotency_key="registration"
    )
    assert (
        await provider.check_template(template=template, metadata=metadata)
    ).available
    prepared = await provider.prepare(
        template=template, metadata=metadata, recipient=recipient, facts={}
    )
    with caplog.at_level("INFO"):
        result = await provider.send(
            recipient=recipient, prepared=prepared, idempotency_key="delivery"
        )
    assert result.status == ProviderState.DELIVERED
    assert 'SMS:sendto:+919876543210:"Hello Alice"' in caplog.text
    changed = Template("sms", {"body": "Updated"}, revision=2)
    assert not (
        await provider.check_template(template=changed, metadata=metadata)
    ).available
    updated = await provider.update_template(
        template=changed, metadata=metadata, idempotency_key="updated"
    )
    assert (await provider.check_template(template=changed, metadata=updated)).available
    await provider.unregister_template(
        template=changed, metadata=updated, idempotency_key="delete"
    )


@pytest.mark.requirement("R22")
async def test_should_prepare_subject_and_alternative_bodies_before_sending(
    email_provider,
):
    prepared = await email_provider.prepare(
        template=Template("notice", {"subject": "Hello $name", "text": "$value"}),
        metadata=None,
        recipient=Recipient("alice", "Alice", "alice@example.com"),
        facts={"value": "literal"},
    )
    assert prepared["subject"] == "Hello Alice"
    assert prepared["text"] == "literal"
    assert prepared["html"] == "<pre>literal</pre>"
