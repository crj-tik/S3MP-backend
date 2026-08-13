from uuid import uuid4

import pytest

from s3mp.common.api.cursor import CursorCodec
from s3mp.common.errors import ApiError


def test_management_cursor_is_bound_to_query_and_context() -> None:
    tenant_id, principal_id = uuid4(), uuid4()
    codec = CursorCodec(b"management-cursor-signing-key-32b")
    token = codec.encode(tenant_id, principal_id, 3, str(uuid4()), query="role_bindings:a")

    assert codec.decode(tenant_id=tenant_id, principal_id=principal_id, authorization_version=3, token=token, query="role_bindings:a")
    with pytest.raises(ApiError) as error:
        codec.decode(tenant_id=tenant_id, principal_id=principal_id, authorization_version=3, token=token, query="role_bindings:b")
    assert error.value.code == "invalid_cursor"
