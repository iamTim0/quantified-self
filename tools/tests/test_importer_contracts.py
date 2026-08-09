"""Tests for the repository-wide importer contract source of truth."""

import json
from pathlib import Path

from tools.generate_importer_contracts import OUTPUT, render
from tools.importer_contracts import (
    CONTRACT_FILENAME,
    contract_paths,
    importer_directories,
    load_contracts,
    validate_all,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_every_importer_has_one_valid_contract():
    """Verifies the importer boundary contract for every discovered service."""
    assert len(importer_directories()) == 8
    assert not validate_all()
    assert all(path.name == CONTRACT_FILENAME for path in contract_paths())


def test_contracts_are_the_source_for_the_generated_catalog():
    """Verifies generated documentation cannot drift from importer contracts."""
    contracts = load_contracts()
    assert OUTPUT.read_text(encoding="utf-8") == render(contracts)


def test_contract_schema_is_repository_local():
    """Verifies each contract points to the checked-in JSON Schema definition."""
    schema = REPO_ROOT / "tools" / "importer-contract.schema.json"
    assert schema.is_file()
    assert all(
        contract["$schema"] == "../../tools/importer-contract.schema.json"
        for contract in contracts_from_files()
    )


def contracts_from_files() -> list[dict[str, object]]:
    """Read the small metadata assertion without importing optional service packages."""
    return [json.loads(path.read_text(encoding="utf-8")) for path in contract_paths()]
