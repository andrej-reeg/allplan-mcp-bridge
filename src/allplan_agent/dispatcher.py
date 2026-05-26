"""Handler registry: maps command names to callables.

Usage::

    @command("create_wall")
    def handle_create_wall(args: dict[str, Any]) -> dict[str, Any]:
        ...
"""

from collections.abc import Callable
from typing import Any

_registry: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}


def command(
    name: str,
) -> Callable[
    [Callable[[dict[str, Any]], dict[str, Any]]],
    Callable[[dict[str, Any]], dict[str, Any]],
]:
    """Decorator that registers a handler function under the given command name."""

    def decorator(
        fn: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> Callable[[dict[str, Any]], dict[str, Any]]:
        if name in _registry:
            raise ValueError(f"Command {name!r} already registered")
        _registry[name] = fn
        return fn

    return decorator


def dispatch(
    cmd_name: str, args: dict[str, Any]
) -> dict[str, Any]:
    """Look up and call the handler for cmd_name.

    Raises KeyError (mapped to InvalidArgs by the caller) for unknown commands.
    """
    handler = _registry.get(cmd_name)
    if handler is None:
        raise KeyError(f"Unknown command: {cmd_name!r}")
    return handler(args)


def registered_commands() -> list[str]:
    return list(_registry.keys())
