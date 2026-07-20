import ast
from pathlib import Path

from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.registry import create_default_registry
from gpt2giga_harness.ui.app import create_app
from gpt2giga_harness.ui.mutation_contracts import (
    CONFORMANCE_EVIDENCE,
    MUTATION_ROUTE_CONTRACTS,
    EnforcementControl,
    MutationClass,
    declared_behaviors,
    mutation_contract_errors,
    required_behaviors,
    unsafe_route_identities,
)


def test_public_unsafe_routes_have_complete_authoritative_mutation_contract(tmp_path):
    app = create_app(
        HarnessConfig(data_dir=str(tmp_path)),
        registry=create_default_registry(include_entry_points=False),
    )

    assert len(MUTATION_ROUTE_CONTRACTS) == 90
    assert {contract.mutation_class for contract in MUTATION_ROUTE_CONTRACTS} == set(
        MutationClass
    )
    assert unsafe_route_identities(app.routes) == {
        contract.identity for contract in MUTATION_ROUTE_CONTRACTS
    }
    assert mutation_contract_errors(app.routes) == ()
    assert app.state.harness_mutation_contracts is MUTATION_ROUTE_CONTRACTS

    for contract in MUTATION_ROUTE_CONTRACTS:
        assert required_behaviors(contract) <= declared_behaviors(contract)
        if contract.control is EnforcementControl.POLICY_ENGINE:
            assert contract.permission_actions
            assert contract.enforcement_owner


def test_mutation_contract_rejects_a_new_unclassified_unsafe_route(tmp_path):
    app = create_app(
        HarnessConfig(data_dir=str(tmp_path)),
        registry=create_default_registry(include_entry_points=False),
    )

    @app.post("/api/new-mutation")
    async def new_mutation():
        return {"mutated": True}

    errors = mutation_contract_errors(app.routes)

    assert any(
        "unclassified unsafe routes" in error
        and "('POST', '/api/new-mutation')" in error
        for error in errors
    )


def test_declared_conformance_evidence_points_to_collected_tests():
    repository_root = Path(__file__).resolve().parents[2]

    for evidence in CONFORMANCE_EVIDENCE.values():
        assert evidence.behaviors
        assert evidence.test_nodes
        for node_id in evidence.test_nodes:
            relative_path, separator, test_name = node_id.partition("::")
            assert separator == "::"
            source_path = repository_root / relative_path
            assert source_path.is_file(), node_id
            tree = ast.parse(source_path.read_text(encoding="utf-8"))
            functions = {
                node.name
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            assert test_name in functions, node_id
