"""Token-safe Redis locks for broker operation execution."""

import asyncio
from collections.abc import Awaitable, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, cast
from uuid import UUID, uuid4

from redis.asyncio import Redis

_RELEASE = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""
_RENEW = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('pexpire', KEYS[1], ARGV[2])
end
return 0
"""


@dataclass(slots=True)
class FileOperationLockSet:
    redis: Redis
    file_ids: Sequence[UUID]
    lease_seconds: int = 60
    _token: str = field(init=False)
    _keys: list[str] = field(init=False)
    _renewal: asyncio.Task[None] | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        self._token = uuid4().hex
        self._keys = [f"s3mp:file-operation-lock:{file_id}" for file_id in sorted(self.file_ids)]
        self._renewal: asyncio.Task[None] | None = None

    async def acquire(self) -> bool:
        acquired: list[str] = []
        try:
            for key in self._keys:
                if not await self.redis.set(
                    key, self._token, nx=True, px=self.lease_seconds * 1000
                ):
                    return False
                acquired.append(key)
        finally:
            if len(acquired) != len(self._keys):
                for key in acquired:
                    await self._eval(_RELEASE, key, self._token)
        if self._keys:
            self._renewal = asyncio.create_task(self._renew())
        return True

    async def release(self) -> None:
        if self._renewal is not None:
            self._renewal.cancel()
            with suppress(asyncio.CancelledError):
                await self._renewal
        for key in self._keys:
            await self._eval(_RELEASE, key, self._token)

    async def _renew(self) -> None:
        while True:
            await asyncio.sleep(max(1, self.lease_seconds // 3))
            for key in self._keys:
                if not await self._eval(_RENEW, key, self._token, str(self.lease_seconds * 1000)):
                    return

    async def _eval(self, script: str, key: str, *args: str) -> Any:
        result = self.redis.eval(script, 1, key, *args)
        return await cast(Awaitable[Any], result)
