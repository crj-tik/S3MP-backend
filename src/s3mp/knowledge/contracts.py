"""Immutable packaged knowledge-contract discovery and integrity checks."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


class KnowledgeContractError(RuntimeError):
    """The deployed knowledge contract is missing or no longer matches its manifest."""


@dataclass(frozen=True)
class KnowledgeContract:
    root: Path
    version: str
    manifest_hash: str

    @property
    def manifest_path(self) -> Path:
        return self.root / "contract-manifest.json"


def default_contract_root() -> Path:
    return (
        Path(__file__).resolve().parent
        / "contract_snapshot"
        / "knowledge-card-extractor"
        / "references"
        / "knowledge-contract"
    )


def load_contract(root: Path | None = None) -> KnowledgeContract:
    """Verify and return the bundled contract without ever mutating it."""
    resolved_root = (root or default_contract_root()).resolve()
    manifest_path = resolved_root / "contract-manifest.json"
    if not manifest_path.is_file():
        raise KnowledgeContractError("knowledge contract manifest is unavailable")
    raw_manifest = manifest_path.read_bytes()
    try:
        manifest = json.loads(raw_manifest)
    except json.JSONDecodeError as exc:
        raise KnowledgeContractError("knowledge contract manifest is invalid JSON") from exc
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise KnowledgeContractError("knowledge contract manifest has no file hashes")
    for relative_path, expected_hash in files.items():
        if not isinstance(relative_path, str) or not isinstance(expected_hash, str):
            raise KnowledgeContractError("knowledge contract manifest contains invalid file entry")
        candidate = (resolved_root / relative_path).resolve()
        if resolved_root not in candidate.parents or not candidate.is_file():
            raise KnowledgeContractError(f"knowledge contract file is unavailable: {relative_path}")
        actual_hash = hashlib.sha256(candidate.read_bytes()).hexdigest()
        if actual_hash != expected_hash:
            raise KnowledgeContractError(f"knowledge contract file hash mismatch: {relative_path}")
    version = manifest.get("ontologyVersion")
    if not isinstance(version, str) or not version:
        raise KnowledgeContractError("knowledge contract has no ontology version")
    return KnowledgeContract(
        root=resolved_root,
        version=version,
        manifest_hash=hashlib.sha256(raw_manifest).hexdigest(),
    )
