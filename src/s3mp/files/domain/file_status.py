"""Lifecycle values for persisted file objects."""

from enum import StrEnum


class FileObjectStatus(StrEnum):
    AVAILABLE = "available"
    DELETING = "deleting"
    DELETE_FAILED = "delete_failed"
    QUARANTINED = "quarantined"
