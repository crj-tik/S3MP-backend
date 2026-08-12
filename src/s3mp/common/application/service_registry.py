"""Application-service registry with fail-fast startup validation."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ServiceRegistry:
    """Collect required service factories and validate them at startup.

    Each entry maps a state attribute name to a factory callable
    that produces the service instance. Startup validation calls
    every factory and fails fast if any service is missing.
    """

    _factories: dict[str, Callable[[], Any]] = field(default_factory=dict)
    _validated: bool = False

    def register(self, name: str, factory: Callable[[], Any]) -> None:
        if self._validated:
            raise RuntimeError("cannot register services after startup validation")
        if name in self._factories:
            raise ValueError(f"service '{name}' is already registered")
        self._factories[name] = factory

    def validate(self) -> dict[str, Any]:
        """Instantiate every registered service and return the populated mapping.

        Fails fast with a clear error if any factory raises.
        """
        if self._validated:
            raise RuntimeError("startup validation has already run")
        services: dict[str, Any] = {}
        errors: list[str] = []
        for name, factory in self._factories.items():
            try:
                services[name] = factory()
            except Exception as exc:
                errors.append(f"  {name}: {exc}")
        if errors:
            raise RuntimeError(
                "application service startup failed:\n" + "\n".join(errors)
            )
        self._validated = True
        return services

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._factories)