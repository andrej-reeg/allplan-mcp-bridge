"""Tests for allplan_agent/dispatcher.py."""

import pytest

from allplan_agent import dispatcher as _mod
from allplan_agent.dispatcher import command, dispatch, registered_commands


@pytest.fixture(autouse=True)
def _reset_registry() -> None:
    """Isolate each test by clearing the shared registry."""
    original = dict(_mod._registry)
    yield
    _mod._registry.clear()
    _mod._registry.update(original)


def test_register_and_dispatch() -> None:
    @command("test_ping")
    def _ping(args: dict) -> dict:  # type: ignore[type-arg]
        return {"pong": True}

    assert dispatch("test_ping", {}) == {"pong": True}


def test_dispatch_passes_args() -> None:
    @command("test_echo")
    def _echo(args: dict) -> dict:  # type: ignore[type-arg]
        return args

    result = dispatch("test_echo", {"value": 42})
    assert result == {"value": 42}


def test_dispatch_unknown_raises_key_error() -> None:
    with pytest.raises(KeyError, match="unknown_cmd"):
        dispatch("unknown_cmd", {})


def test_duplicate_registration_raises() -> None:
    @command("test_dup")
    def _first(args: dict) -> dict:  # type: ignore[type-arg]
        return {}

    with pytest.raises(ValueError, match="already registered"):
        @command("test_dup")
        def _second(args: dict) -> dict:  # type: ignore[type-arg]
            return {}


def test_registered_commands_returns_all() -> None:
    @command("test_cmd_a")
    def _a(args: dict) -> dict:  # type: ignore[type-arg]
        return {}

    @command("test_cmd_b")
    def _b(args: dict) -> dict:  # type: ignore[type-arg]
        return {}

    cmds = registered_commands()
    assert "test_cmd_a" in cmds
    assert "test_cmd_b" in cmds
