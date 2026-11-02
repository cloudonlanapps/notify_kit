import httpx
import pytest
from app.main import create_app
from app.providers.console import ConsoleProvider
from app.providers.fake_sms import FakeSmsProvider


@pytest.fixture
async def api(migrated_path):
    app = create_app(
        start_worker=False,
        database_url=f"sqlite+aiosqlite:///{migrated_path}",
        registered_providers={"console": ConsoleProvider(), "sms": FakeSmsProvider()},
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://example"
        ) as client:
            yield client


@pytest.mark.requirement("R10")
async def test_should_expose_template_delivery_and_status_when_http_endpoints_are_used(
    api, caplog
):
    created = await api.post(
        "/v1/templates",
        json={"label": "greeting", "definition": {"body": "Hello $name"}},
    )
    assert created.status_code == 201
    query = await api.get("/v1/templates/greeting")
    assert query.json()["definition"] == {"body": "Hello $name"}
    sent = await api.post(
        "/v1/notifications",
        json={
            "provider": "console",
            "template": "greeting",
            "recipients": [{"username": "alice", "name": "Alice"}],
            "facts": {},
            "idempotency_key": "http",
        },
    )
    assert sent.status_code == 202
    delivery_id = sent.json()["deliveries"][0]["id"]
    before = await api.get(f"/v1/notifications/deliveries/{delivery_id}")
    assert before.json()["status"] == "queued"
    with caplog.at_level("INFO"):
        result = await api.post("/v1/worker/run-once", json={"max_jobs": 10})
    assert result.status_code == 200
    assert result.json()[0]["status"] == "delivered"
    assert "Hello Alice" in caplog.text


@pytest.mark.requirement("R20")
async def test_should_report_individual_error_when_sms_recipient_has_no_phone(
    api, caplog
):
    created = await api.post(
        "/v1/templates", json={"label": "sms", "definition": {"body": "Hello $name"}}
    )
    assert created.status_code == 201
    registration = await api.post("/v1/templates/sms/providers/sms/register")
    assert registration.status_code == 200
    assert registration.json()["metadata"]["template_id"]
    batch = await api.post(
        "/v1/notifications",
        json={
            "provider": "sms",
            "template": "sms",
            "recipients": [
                {"username": "alice", "name": "Alice", "phone": "+919876543210"},
                {"username": "bob"},
            ],
            "facts": {},
            "idempotency_key": "sms-http",
        },
    )
    assert batch.status_code == 202
    statuses = await api.get(f"/v1/notifications/batches/{batch.json()['batch_id']}")
    assert statuses.json()[1]["error_code"] == "recipient_invalid"
    with caplog.at_level("INFO"):
        result = await api.post("/v1/worker/run-once", json={"max_jobs": 10})
    assert result.status_code == 200
    assert 'SMS:sendto:+919876543210:"Hello Alice"' in caplog.text


@pytest.mark.requirement("R28")
async def test_should_use_typed_schemas_when_preview_and_acknowledge_endpoints_are_called(
    api,
):
    response = await api.post(
        "/v1/templates",
        json={"label": "greeting", "definition": {"body": "Hello $name"}},
    )
    assert response.status_code == 201
    preview = await api.post(
        "/v1/notifications/preview",
        json={
            "provider": "console",
            "template": "greeting",
            "recipient": {"username": "alice", "name": "Alice"},
            "facts": {},
        },
    )
    assert preview.status_code == 200
    assert preview.json()["payload"]["body"] == "Hello Alice"
    schema = await api.get("/openapi.json")
    assert "PreviewRequest" in schema.json()["components"]["schemas"]


@pytest.mark.requirement("R8")
async def test_should_reject_request_when_http_input_or_provider_is_invalid(api):
    response = await api.post("/v1/notifications", json={"provider": "console"})
    assert response.status_code == 422
    unknown = await api.get("/v1/providers/missing")
    assert unknown.status_code == 404
    assert unknown.json()["code"] == "provider_not_registered"


@pytest.mark.requirement("R40")
async def test_should_process_automatically_when_fastapi_lifespan_starts_worker(
    migrated_path,
):
    import asyncio

    app = create_app(
        database_url=f"sqlite+aiosqlite:///{migrated_path}",
        registered_providers={"console": ConsoleProvider()},
    )
    async with asyncio.timeout(5):
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://example"
            ) as client:
                created = await client.post(
                    "/v1/templates",
                    json={"label": "auto", "definition": {"body": "Hi $username"}},
                )
                assert created.status_code == 201
                sent = await client.post(
                    "/v1/notifications",
                    json={
                        "provider": "console",
                        "template": "auto",
                        "recipients": [{"username": "alice"}],
                        "facts": {},
                        "idempotency_key": "auto",
                    },
                )
                assert sent.status_code == 202
                delivery_id = sent.json()["deliveries"][0]["id"]
                while True:
                    response = await client.get(
                        f"/v1/notifications/deliveries/{delivery_id}"
                    )
                    assert response.status_code == 200
                    if response.json()["status"] == "delivered":
                        break
                    await asyncio.sleep(0.01)
                assert response.json()["terminal"]
