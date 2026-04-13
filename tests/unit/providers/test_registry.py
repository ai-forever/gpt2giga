from gpt2giga.providers import (
    get_provider_descriptor,
    iter_enabled_provider_descriptors,
    list_provider_descriptors,
)
from gpt2giga.providers.contracts import (
    BatchesProviderAdapter,
    ChatProviderAdapter,
    EmbeddingsProviderAdapter,
    FilesProviderAdapter,
    ModelsProviderAdapter,
    ResponsesProviderAdapter,
)


def test_builtin_provider_registry_lists_expected_descriptors():
    descriptors = list_provider_descriptors()

    assert [descriptor.name for descriptor in descriptors] == [
        "openai",
        "anthropic",
        "gemini",
    ]


def test_openai_provider_descriptor_exposes_mounts_and_adapters():
    descriptor = get_provider_descriptor("openai")

    assert descriptor.display_name == "OpenAI"
    assert "litellm_model_info" in descriptor.capabilities
    assert "/v1/model/info" in descriptor.routes
    assert [(mount.prefix, mount.auth_policy) for mount in descriptor.mounts] == [
        ("", "default"),
        ("/v1", "default"),
        ("/v1", "default"),
        ("", "default"),
    ]
    assert isinstance(descriptor.adapters.chat, ChatProviderAdapter)
    assert isinstance(descriptor.adapters.responses, ResponsesProviderAdapter)
    assert isinstance(descriptor.adapters.embeddings, EmbeddingsProviderAdapter)
    assert isinstance(descriptor.adapters.models, ModelsProviderAdapter)
    assert isinstance(descriptor.adapters.files, FilesProviderAdapter)
    assert isinstance(descriptor.adapters.batches, BatchesProviderAdapter)


def test_gemini_provider_descriptor_uses_gemini_auth_policy():
    descriptor = get_provider_descriptor("gemini")

    assert {mount.prefix for mount in descriptor.mounts} == {
        "/v1beta",
        "/upload/v1beta",
    }
    assert all(mount.auth_policy == "gemini" for mount in descriptor.mounts)


def test_iter_enabled_provider_descriptors_filters_registry():
    enabled = iter_enabled_provider_descriptors(["anthropic", "gemini"])

    assert [descriptor.name for descriptor in enabled] == ["anthropic", "gemini"]
