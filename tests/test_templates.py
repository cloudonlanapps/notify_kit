import pytest

from notify_kit import DeliveryState, ErrorCode, NotifierError, Recipient


@pytest.mark.requirement("R15")
async def test_should_increment_revision_when_template_crud_is_performed(kit):
    notifier, _, _ = kit
    created = await notifier.templates.create(
        label="second", definition={"title": "hello"}
    )
    assert created.revision == 1
    assert (await notifier.templates.get("second")).definition == {"title": "hello"}
    updated = await notifier.templates.update(
        label="second", definition={"title": "changed"}
    )
    assert updated.revision == 2
    assert [t.label for t in await notifier.templates.list()] == ["receipt", "second"]
    await notifier.templates.delete("second")
    with pytest.raises(NotifierError) as error:
        await notifier.templates.get("second")
    assert error.value.code == ErrorCode.NOT_FOUND


@pytest.mark.requirement("R17")
@pytest.mark.parametrize("operation", ["create", "update", "delete"])
async def test_should_reject_operation_when_template_is_duplicate_or_missing(
    kit, operation
):
    notifier, _, _ = kit
    with pytest.raises(NotifierError) as error:
        if operation == "create":
            await notifier.templates.create(label="receipt", definition={})
        elif operation == "update":
            await notifier.templates.update(label="missing", definition={})
        else:
            await notifier.templates.delete("missing")
    assert error.value.code == (
        ErrorCode.ALREADY_EXISTS if operation == "create" else ErrorCode.NOT_FOUND
    )


@pytest.mark.requirement("R16")
async def test_should_keep_separate_links_when_registering_multiple_templates_to_one_provider(
    kit,
):
    notifier, provider, _ = kit
    await notifier.templates.create(label="other", definition={})
    assert (
        await notifier.template_register(provider="primary", template="receipt") == {}
    )
    assert await notifier.template_register(provider="primary", template="other") == {}
    assert (
        await notifier.template_status(provider="primary", template="receipt")
    ) == {}


@pytest.mark.requirement("R20")
async def test_should_preserve_identifiers_and_parameter_order_when_provider_prepares_template(
    kit,
):
    notifier, provider, _ = kit
    definition = {
        "approved_id": "external-123",
        "parameters": ["name", "amount"],
        "language": "en",
    }
    await notifier.templates.update(label="receipt", definition=definition)
    provider.metadata = {"template_id": "gateway-456", "approved": True}
    assert (
        await notifier.template_register(provider="primary", template="receipt")
        == provider.metadata
    )
    preview = await notifier.preview(
        provider="primary", template="receipt", recipient=Recipient("alice"), facts={}
    )
    assert preview["definition"] == definition


@pytest.mark.requirement("R27")
async def test_should_select_exact_label_when_language_variants_exist(kit):
    notifier, _, _ = kit
    with pytest.raises(NotifierError) as error:
        await notifier.preview(
            provider="primary",
            template="receipt_hi",
            recipient=Recipient("alice"),
            facts={},
        )
    assert error.value.code == ErrorCode.NOT_FOUND


@pytest.mark.requirement("R9")
async def test_should_check_template_when_link_metadata_is_empty(kit):
    notifier, provider, _ = kit
    assert (
        await notifier.template_status(provider="primary", template="receipt") is None
    )
    await notifier.preview(
        provider="primary", template="receipt", recipient=Recipient("alice"), facts={}
    )
    assert provider.checks == []
    await notifier.template_register(provider="primary", template="receipt")
    await notifier.preview(
        provider="primary", template="receipt", recipient=Recipient("alice"), facts={}
    )
    assert provider.checks == ["receipt"]


@pytest.mark.requirement("R17")
async def test_should_block_stale_link_when_local_definition_has_changed(kit):
    notifier, _, _ = kit
    await notifier.template_register(provider="primary", template="receipt")
    await notifier.templates.update(label="receipt", definition={"body": "new"})
    with pytest.raises(NotifierError) as error:
        await notifier.preview(
            provider="primary",
            template="receipt",
            recipient=Recipient("alice"),
            facts={},
        )
    assert error.value.code == ErrorCode.TEMPLATE_CHANGED
    assert await notifier.template_update(provider="primary", template="receipt") == {
        "revision": 2
    }
    assert (
        await notifier.preview(
            provider="primary",
            template="receipt",
            recipient=Recipient("alice"),
            facts={},
        )
    )["definition"] == {"body": "new"}


@pytest.mark.requirement("R17")
async def test_should_keep_link_and_block_delete_when_provider_unregister_fails(kit):
    notifier, provider, _ = kit
    await notifier.template_register(provider="primary", template="receipt")
    provider.fail_unregister = True
    with pytest.raises(NotifierError) as error:
        await notifier.template_unregister(provider="primary", template="receipt")
    assert error.value.code == ErrorCode.PROVIDER_ACTION_REQUIRED
    assert await notifier.template_status(provider="primary", template="receipt") == {}
    with pytest.raises(NotifierError) as error:
        await notifier.templates.delete("receipt")
    assert error.value.code == ErrorCode.TEMPLATE_HAS_LINKS
    provider.fail_unregister = False
    await notifier.template_unregister(provider="primary", template="receipt")
    assert (
        await notifier.template_status(provider="primary", template="receipt") is None
    )
    await notifier.templates.delete("receipt")
    assert await notifier.templates.list() == ()


@pytest.mark.requirement("R17")
async def test_should_prevent_template_mutation_when_snapshot_is_pending(kit):
    notifier, _, _ = kit
    await notifier.send(
        provider="primary",
        template="receipt",
        recipients=[Recipient("alice")],
        facts={},
        idempotency_key="pending",
    )
    with pytest.raises(NotifierError) as error:
        await notifier.templates.update(label="receipt", definition={})
    assert error.value.code == ErrorCode.TEMPLATE_IN_USE
    assert (await notifier.run_once())[0].status == DeliveryState.DELIVERED
    assert (
        await notifier.templates.update(label="receipt", definition={})
    ).revision == 2


@pytest.mark.requirement("R17")
async def test_should_use_new_operation_key_when_template_is_unregistered_and_registered_again(
    kit, monkeypatch
):
    notifier, provider, _ = kit
    keys = []
    original = provider.register_template

    async def record(**kwargs):
        keys.append(kwargs["idempotency_key"])
        return await original(**kwargs)

    monkeypatch.setattr(provider, "register_template", record)
    await notifier.template_register(provider="primary", template="receipt")
    await notifier.template_unregister(provider="primary", template="receipt")
    await notifier.template_register(provider="primary", template="receipt")
    assert len(keys) == 2 and keys[0] != keys[1]
