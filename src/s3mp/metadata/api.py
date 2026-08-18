"""Public, read-only platform metadata catalog endpoint."""

from fastapi import APIRouter

from s3mp.metadata.catalog import MetadataCatalogResponse, catalog_payload

router = APIRouter(prefix="/api/v1/metadata", tags=["Metadata"])


@router.get("/catalog", response_model=MetadataCatalogResponse, operation_id="get_metadata_catalog")
def get_metadata_catalog() -> MetadataCatalogResponse:
    """Return stable non-sensitive enum and lifecycle metadata for clients."""
    return MetadataCatalogResponse.model_validate(catalog_payload())
