"""Card rendering and validation against the bundled ontology schema."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from s3mp.knowledge.contracts import KnowledgeContract


class CardValidationError(ValueError):
    """A model response cannot be persisted as a contract card."""


@dataclass(frozen=True)
class ParsedCard:
    card_id: str
    card_type: str
    frontmatter: dict[str, Any]
    body: str


def contract_indexed_attributes(contract: KnowledgeContract) -> frozenset[str]:
    schema = _load_yaml(contract.root / "ontology" / "schema.yaml")
    attributes = schema.get("attributes", {})
    if not isinstance(attributes, dict):
        raise CardValidationError("ontology attributes are invalid")
    return frozenset(
        name
        for name, definition in attributes.items()
        if isinstance(definition, dict) and definition.get("index")
    )


def parse_card(markdown: str, *, contract: KnowledgeContract) -> ParsedCard:
    """Validate the minimum portable YAML/Markdown card envelope."""
    if not markdown.startswith("---\n"):
        raise CardValidationError("card must begin with YAML frontmatter")
    marker = markdown.find("\n---\n", 4)
    if marker < 0:
        raise CardValidationError("card frontmatter is not closed")
    raw_frontmatter, body = markdown[4:marker], markdown[marker + 5 :].strip()
    frontmatter = yaml.safe_load(raw_frontmatter)
    if not isinstance(frontmatter, dict):
        raise CardValidationError("card frontmatter must be a mapping")
    card_id, card_type = frontmatter.get("id"), frontmatter.get("type")
    if not isinstance(card_id, str) or not card_id:
        raise CardValidationError("card id is required")
    if not isinstance(card_type, str) or card_type not in _card_types(contract):
        raise CardValidationError("card type is not allowed by the ontology")
    if not body:
        raise CardValidationError("card body is required")
    return ParsedCard(card_id=card_id, card_type=card_type, frontmatter=frontmatter, body=body)


def render_card(frontmatter: dict[str, Any], body: str, *, contract: KnowledgeContract) -> str:
    frontmatter_yaml = yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False)
    rendered = f"---\n{frontmatter_yaml}---\n\n{body.strip()}\n"
    parse_card(rendered, contract=contract)
    return rendered


def indexed_metadata(card: ParsedCard, *, contract: KnowledgeContract) -> dict[str, Any]:
    allowed = contract_indexed_attributes(contract)
    metadata = {name: card.frontmatter[name] for name in allowed if name in card.frontmatter}
    for name in ("status", "provenance", "sourceLocations"):
        if name in card.frontmatter:
            metadata[name] = card.frontmatter[name]
    return metadata


def _card_types(contract: KnowledgeContract) -> set[str]:
    schema = _load_yaml(contract.root / "ontology" / "schema.yaml")
    values = schema.get("capabilities", {}).get("card_types", [])
    return {value for value in values if isinstance(value, str)}


def _load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise CardValidationError(f"invalid ontology file: {path.name}")
    return data
