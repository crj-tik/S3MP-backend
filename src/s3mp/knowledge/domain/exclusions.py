"""Application-relative directory exclusion matching."""

from pathlib import PurePosixPath


class InvalidExclusionPath(ValueError):
    """An exclusion path would be ambiguous or escape an application root."""


def normalize_directory_path(value: str) -> str:
    """Return a stable app-relative directory path without a leading slash."""
    if not value or not value.strip():
        raise InvalidExclusionPath("directory path is required")
    raw = value.strip().replace("\\", "/")
    if raw == "/":
        return ""
    if raw.startswith("/"):
        raise InvalidExclusionPath("directory path must be application-relative")
    parts = [part for part in PurePosixPath(raw).parts if part not in {".", ""}]
    if not parts or any(part == ".." for part in parts):
        raise InvalidExclusionPath("directory path must not contain traversal segments")
    return "/".join(parts)


def is_excluded(object_key: str, directory_path: str) -> bool:
    """Match the selected directory itself and every descendant by path segment."""
    normalized_key = normalize_directory_path(object_key)
    normalized_rule = normalize_directory_path(directory_path)
    if not normalized_rule:
        return True
    return normalized_key == normalized_rule or normalized_key.startswith(f"{normalized_rule}/")
