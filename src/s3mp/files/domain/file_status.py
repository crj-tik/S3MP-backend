"""Lifecycle values for persisted file objects."""

from enum import StrEnum


class FileObjectStatus(StrEnum):
    AVAILABLE = "available"
    RENAMING = "renaming"
    RENAME_FAILED = "rename_failed"
    DELETING = "deleting"
    DELETED = "deleted"
    DELETE_FAILED = "delete_failed"
    QUARANTINED = "quarantined"
