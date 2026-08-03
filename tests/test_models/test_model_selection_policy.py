import pytest

from gpt2giga.models.catalog import ModelSelectionPolicy


@pytest.mark.parametrize(
    ("policy", "requested", "expected_model", "expected_source"),
    [
        (
            ModelSelectionPolicy(default_model="default", forced_model="forced"),
            "requested",
            "forced",
            "forced",
        ),
        (
            ModelSelectionPolicy(default_model="default"),
            "requested",
            "requested",
            "requested",
        ),
        (
            ModelSelectionPolicy(default_model="default"),
            None,
            "default",
            "default",
        ),
        (ModelSelectionPolicy(), None, None, "omitted"),
    ],
)
def test_model_selection_policy_has_explicit_precedence(
    policy,
    requested,
    expected_model,
    expected_source,
):
    selection = policy.select(requested)

    assert selection.model == expected_model
    assert selection.source == expected_source


def test_blank_values_do_not_become_default_or_forced_models():
    policy = ModelSelectionPolicy(default_model=" ", forced_model="")

    assert policy.default_model is None
    assert policy.forced_model is None
    assert policy.select("  ").source == "omitted"
