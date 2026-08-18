"""Lifecycle values for platform support-access requests."""

from enum import StrEnum


class SupportAccessStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REVOKED = "revoked"
    EXPIRED = "expired"
