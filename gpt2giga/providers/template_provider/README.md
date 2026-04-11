# Template Provider Scaffold

Copy this directory to `gpt2giga/providers/<provider>/` when adding a new external provider.

Checklist:
- Implement only the supported capability adapters in `capabilities.py`.
- Keep FastAPI transport handlers in `gpt2giga/api/<provider>/`.
- Put request normalization in `request_adapter.py`.
- Put response shaping in `response_presenter.py`.
- Put stream formatting in `stream_presenter.py`.
- Register the provider descriptor in `gpt2giga/providers/registry.py`.
- Add compatibility fixtures/tests under `tests/compat/<provider>/`.
- Add examples and capability docs.
