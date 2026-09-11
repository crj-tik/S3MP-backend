"""Operator-only controlled replay for a dead-lettered file operation."""

import argparse
import asyncio
from uuid import UUID

from s3mp.common.config import get_settings
from s3mp.common.database import create_engine, create_session_factory
from s3mp.files.infrastructure.repositories import SqlAlchemyFileStore


async def main(tenant_id: UUID, operation_id: UUID, event_id: UUID) -> None:
    settings = get_settings()
    database_url = settings.secret_value("database_url")
    if not database_url:
        raise RuntimeError("database configuration is required")
    engine = create_engine(database_url)
    try:
        operation = await SqlAlchemyFileStore(
            create_session_factory(engine)
        ).replay_dead_letter_operation(tenant_id, operation_id, event_id)
        if operation is None:
            raise RuntimeError("operation is not replayable")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("tenant_id", type=UUID)
    parser.add_argument("operation_id", type=UUID)
    parser.add_argument("event_id", type=UUID)
    args = parser.parse_args()
    asyncio.run(main(args.tenant_id, args.operation_id, args.event_id))
