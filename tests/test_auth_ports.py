import pytest

from s3mp.identity.domain.auth import AuthenticatedIdentity, ExternalSubject


def test_external_subject_is_case_sensitive_mapping_value() -> None:
    upper = ExternalSubject("https://issuer.example", "Alice")
    lower = ExternalSubject("https://issuer.example", "alice")
    assert upper != lower
    assert AuthenticatedIdentity(upper.issuer, upper.subject).external_subject == upper


@pytest.mark.parametrize(
    ("issuer", "subject"),
    [("", "subject"), ("   ", "subject"), ("https://issuer.example", "")],
)
def test_external_subject_rejects_empty_components(issuer: str, subject: str) -> None:
    with pytest.raises(ValueError):
        ExternalSubject(issuer, subject)
