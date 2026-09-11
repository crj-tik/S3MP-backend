"""Helpers for recovering deterministic public references on legacy files."""

from uuid import UUID

from s3mp.files.infrastructure.models import FileObjectModel
from s3mp.storage.domain.policy import derive_provider_target
from s3mp.storage.infrastructure.models import StorageSpaceModel


def relative_key_for_file(file_obj: FileObjectModel, space: StorageSpaceModel) -> str:
    """Recover the canonical relative key from a stored physical provider key."""
    version = file_obj.provider_target_version
    if version != space.provider_target_version:
        raise ValueError("provider_target_version_mismatch")

    # FileObject stores the namespace used when it was created.  Prefer it so
    # a later namespace rotation does not make historical objects ambiguous.
    namespaces = tuple(dict.fromkeys((file_obj.storage_namespace, space.storage_namespace, None)))
    for storage_namespace in namespaces:
        namespace_key = derive_provider_target(
            tenant_id=file_obj.tenant_id,
            storage_space_id=file_obj.storage_space_id,
            bucket=space.bucket,
            relative_key="",
            operator_prefix=space.root_prefix,
            storage_namespace=storage_namespace,
            version=version,
        ).key.rstrip("/")
        prefix = namespace_key + "/"
        if file_obj.object_key.startswith(prefix):
            relative_key = file_obj.object_key[len(prefix) :]
            if relative_key:
                return relative_key
    raise ValueError("physical_key_outside_storage_namespace")


def application_id_for_file(file_obj: FileObjectModel, space: StorageSpaceModel) -> UUID:
    """Use the record scope, falling back to its application-owned storage space."""
    if file_obj.application_id is not None and space.application_id is not None:
        if file_obj.application_id != space.application_id:
            raise ValueError("application_scope_mismatch")
    application_id = file_obj.application_id or space.application_id
    if application_id is None:
        raise ValueError("missing_application_id")
    return application_id
