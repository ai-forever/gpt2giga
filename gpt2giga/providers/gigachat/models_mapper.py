"""GigaChat model-discovery mapping entry point."""

from __future__ import annotations

from typing import Any

from gpt2giga.features.models.contracts import ModelDescriptor, ModelListData


class GigaChatModelsMapper:
    """Wrap model-discovery mapping for the GigaChat provider."""

    def list_descriptors(self, response: Any) -> ModelListData:
        """Convert a provider models response into internal descriptors."""
        data = getattr(response, "data", None) or []
        return [self.build_descriptor(model_obj) for model_obj in data]

    def build_descriptor(
        self,
        model_obj: Any,
        *,
        kind: str = "generation",
    ) -> ModelDescriptor:
        """Convert a provider model object into an internal descriptor."""
        payload = _model_payload(model_obj)
        model_id = _extract_model_id(model_obj, payload)
        object_type = (
            _first_string(
                payload.get("object"),
                payload.get("object_"),
                getattr(model_obj, "object_", None),
                getattr(model_obj, "object", None),
                default="model",
            )
            or "model"
        )
        default_owner = "gpt2giga" if kind == "embeddings" else "gigachat"
        owned_by = (
            _first_string(
                payload.get("owned_by"),
                getattr(model_obj, "owned_by", None),
                default=default_owner,
            )
            or default_owner
        )
        return {
            "id": model_id,
            "object": object_type,
            "owned_by": owned_by,
            "kind": kind,
        }

    def build_embeddings_descriptor(self, model_id: str) -> ModelDescriptor:
        """Build an internal descriptor for the configured embeddings model."""
        return {
            "id": model_id,
            "object": "model",
            "owned_by": "gpt2giga",
            "kind": "embeddings",
        }


def _model_payload(model_obj: Any) -> dict[str, Any]:
    if isinstance(model_obj, dict):
        return model_obj
    if hasattr(model_obj, "model_dump"):
        payload = model_obj.model_dump(by_alias=True)
        if isinstance(payload, dict):
            return payload
    return {}


def _extract_model_id(model_obj: Any, payload: dict[str, Any]) -> str:
    model_id = _first_string(
        payload.get("id"),
        payload.get("id_"),
        payload.get("name"),
        getattr(model_obj, "id_", None),
        getattr(model_obj, "id", None),
        getattr(model_obj, "name", None),
    )
    if model_id is None:
        raise AttributeError("Model object must expose `id`, `id_`, or `name`.")
    return model_id


def _first_string(*values: Any, default: str | None = None) -> str | None:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return default
