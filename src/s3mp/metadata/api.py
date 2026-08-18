"""Public, read-only platform metadata catalog endpoint."""

from typing import Annotated

from fastapi import APIRouter, Query

from s3mp.common.errors import ApiError
from s3mp.metadata.catalog import MetadataCatalogResponse, catalog_payload

router = APIRouter(prefix="/api/v1/metadata", tags=["Metadata"])


@router.get("/catalog", response_model=MetadataCatalogResponse, operation_id="get_metadata_catalog")
def get_metadata_catalog(
    domains: Annotated[
        list[str] | None, Query(description="按业务域过滤，可重复传入。")
    ] = None,
) -> MetadataCatalogResponse:
    """Return stable non-sensitive enum and lifecycle metadata for clients."""
    try:
        return MetadataCatalogResponse.model_validate(catalog_payload(domains))
    except ValueError as error:
        raise ApiError("validation_failed", str(error), status_code=422) from error
