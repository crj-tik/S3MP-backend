"""Contract-derived prompt assembly and candidate-card validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import yaml

from s3mp.knowledge.application.card_contract import CardValidationError, render_card
from s3mp.knowledge.application.text_extraction import EvidenceChunk
from s3mp.knowledge.contracts import KnowledgeContract


@dataclass(frozen=True)
class ValidatedDraft:
    card_id: str
    card_type: str
    markdown: str
    source_locations: tuple[dict[str, Any], ...]
    confidence: str


def assemble_prompt(
    *, contract: KnowledgeContract, chunks: tuple[EvidenceChunk, ...], source_id: str
) -> str:
    """Create deterministic instructions from the immutable ontology resources."""
    schema = (contract.root / "ontology" / "schema.yaml").read_text(encoding="utf-8")
    template_names = (
        "metric",
        "table",
        "concept",
        "policy",
        "attribution",
        "equation",
        "action",
        "org",
        "tool",
    )
    templates = {
        name: (contract.root / "schema" / "templates" / f"{name}.md").read_text(encoding="utf-8")
        for name in template_names
    }
    evidence = [{"text": chunk.text, "locations": list(chunk.locations)} for chunk in chunks]
    return (
        "You extract governed knowledge cards. Return JSON only: {cards: [...], unresolved: [...], "
        "conflicts: [...], ontologyProposals: [...]}. Every card must be draft, ai_extracted, "
        "include sourceLocations referencing the supplied source ID, and never invent "
        "missing facts.\n"
        f"Contract version: {contract.version}; source ID: {source_id}\n"
        f"Ontology:\n{schema}\nTemplates:\n{json.dumps(templates, ensure_ascii=False)}\n"
        f"Evidence:\n{json.dumps(evidence, ensure_ascii=False)}"
    )


def validate_draft(
    candidate: dict[str, Any], *, contract: KnowledgeContract, source_id: str
) -> ValidatedDraft:
    required = {"type", "id", "status", "provenance", "content", "sourceLocations", "confidence"}
    missing = required.difference(candidate)
    if missing:
        raise CardValidationError(f"card draft missing fields: {', '.join(sorted(missing))}")
    card_type = candidate["type"]
    if card_type not in _card_types(contract):
        raise CardValidationError("card type is not in the ontology")
    if candidate["status"] != "draft" or candidate["provenance"] != "ai_extracted":
        raise CardValidationError("model cards must be draft ai_extracted cards")
    if candidate["confidence"] not in {"high", "medium", "low"}:
        raise CardValidationError("card confidence is invalid")
    locations = candidate["sourceLocations"]
    if not isinstance(locations, list) or not locations:
        raise CardValidationError("card sourceLocations must not be empty")
    if any(
        not isinstance(location, dict) or location.get("sourceId") != source_id
        for location in locations
    ):
        raise CardValidationError("card sourceLocations contain an unknown source")
    content = candidate["content"]
    if not isinstance(content, str) or not content.strip():
        raise CardValidationError("card content is required")
    frontmatter = dict(candidate.get("frontmatter") or {})
    _validate_controlled_values(frontmatter, contract)
    frontmatter.update(
        {
            "id": candidate["id"],
            "type": card_type,
            "status": "draft",
            "provenance": "ai_extracted",
            "sourceLocations": locations,
        }
    )
    return ValidatedDraft(
        card_id=str(candidate["id"]),
        card_type=card_type,
        markdown=render_card(frontmatter, content, contract=contract),
        source_locations=tuple(locations),
        confidence=candidate["confidence"],
    )


def _card_types(contract: KnowledgeContract) -> set[str]:
    schema = yaml.safe_load(
        (contract.root / "ontology" / "schema.yaml").read_text(encoding="utf-8")
    )
    return set(schema.get("capabilities", {}).get("card_types", []))


def _validate_controlled_values(frontmatter: dict[str, Any], contract: KnowledgeContract) -> None:
    schema = yaml.safe_load(
        (contract.root / "ontology" / "schema.yaml").read_text(encoding="utf-8")
    )
    vocabularies = yaml.safe_load(
        (contract.root / "ontology" / "vocabularies.yaml").read_text(encoding="utf-8")
    )
    attributes = schema.get("attributes", {})
    for name, definition in attributes.items():
        if name not in frontmatter or not isinstance(definition, dict):
            continue
        value_spec = definition.get("value")
        vocab_name = value_spec.get("vocab") if isinstance(value_spec, dict) else None
        if not vocab_name:
            continue
        allowed = _flatten_vocab(vocabularies.get(vocab_name, []))
        values = frontmatter[name] if isinstance(frontmatter[name], list) else [frontmatter[name]]
        if any(value not in allowed for value in values):
            raise CardValidationError(
                f"frontmatter field {name!r} contains a value outside {vocab_name}"
            )


def _flatten_vocab(value: Any) -> set[Any]:
    if isinstance(value, dict):
        result: set[Any] = set()
        for item in value.values():
            result.update(_flatten_vocab(item))
        return result
    if isinstance(value, list):
        result = set()
        for item in value:
            result.update(_flatten_vocab(item))
        return result
    return {value}
