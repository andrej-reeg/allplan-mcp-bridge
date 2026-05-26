"""Tests for allplan_agent/main_loop.py — pump_once() behaviour."""

import time
from concurrent.futures import Future
from typing import Any

import pytest

from allplan_agent import dispatcher as _dispatch_mod
from allplan_agent.command_queue import Command, CommandQueue
from allplan_agent.dispatcher import command
from allplan_agent.main_loop import pump_once


@pytest.fixture(autouse=True)
def _reset_registry() -> None:
    original = dict(_dispatch_mod._registry)
    yield
    _dispatch_mod._registry.clear()
    _dispatch_mod._registry.update(original)


def _make_cmd(
    cmd_name: str, deadline_offset: float = 10.0
) -> tuple[Command, "Future[dict[str, Any]]"]:
    fut: Future[dict[str, Any]] = Future()
    cmd = Command(
        id="test-id",
        cmd_name=cmd_name,
        args={},
        future=fut,
        deadline_at=time.monotonic() + deadline_offset,
    )
    return cmd, fut


def test_pump_runs_handler_and_resolves_future() -> None:
    @command("test_noop")
    def _noop(args: dict[str, Any]) -> dict[str, Any]:
        return {"done": True}

    q = CommandQueue()
    cmd, fut = _make_cmd("test_noop")
    q.enqueue(cmd)

    count = pump_once(q)
    assert count == 1
    assert fut.done()
    assert fut.result() == {"done": True}


def test_pump_captures_handler_exception() -> None:
    @command("test_boom")
    def _boom(args: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("handler exploded")

    q = CommandQueue()
    cmd, fut = _make_cmd("test_boom")
    q.enqueue(cmd)

    count = pump_once(q)
    assert count == 1
    assert fut.done()
    with pytest.raises(RuntimeError, match="handler exploded"):
        fut.result()


def test_pump_loop_survives_bad_command() -> None:
    """One failing command must not prevent the next from running."""
    @command("test_fail")
    def _fail(args: dict[str, Any]) -> dict[str, Any]:
        raise ValueError("oops")

    @command("test_ok")
    def _ok(args: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True}

    q = CommandQueue()
    fail_fut: Future[dict[str, Any]] = Future()
    ok_fut: Future[dict[str, Any]] = Future()

    q.enqueue(Command(id="1", cmd_name="test_fail", args={}, future=fail_fut,
                      deadline_at=time.monotonic() + 10))
    q.enqueue(Command(id="2", cmd_name="test_ok", args={}, future=ok_fut,
                      deadline_at=time.monotonic() + 10))

    pump_once(q, max_items=8)

    assert fail_fut.exception() is not None
    assert ok_fut.result() == {"ok": True}


def test_deadline_exceeded_skips_handler() -> None:
    call_count = [0]

    @command("test_slow")
    def _slow(args: dict[str, Any]) -> dict[str, Any]:
        call_count[0] += 1
        return {}

    q = CommandQueue()
    fut: Future[dict[str, Any]] = Future()
    expired = Command(
        id="x", cmd_name="test_slow", args={}, future=fut,
        deadline_at=time.monotonic() - 1.0,  # already expired
    )
    q.enqueue(expired)
    pump_once(q)

    assert call_count[0] == 0  # handler never ran
    assert fut.done()
    with pytest.raises(TimeoutError):
        fut.result()


def test_unknown_command_resolves_future_with_error() -> None:
    q = CommandQueue()
    fut: Future[dict[str, Any]] = Future()
    cmd = Command(id="z", cmd_name="no_such_cmd", args={}, future=fut,
                  deadline_at=time.monotonic() + 10)
    q.enqueue(cmd)
    pump_once(q)

    assert fut.done()
    with pytest.raises(KeyError):
        fut.result()


def test_pump_drains_up_to_max_items() -> None:
    @command("test_multi")
    def _multi(args: dict[str, Any]) -> dict[str, Any]:
        return {}

    q = CommandQueue()
    futures = []
    for i in range(5):
        fut: Future[dict[str, Any]] = Future()
        futures.append(fut)
        q.enqueue(Command(id=str(i), cmd_name="test_multi", args={}, future=fut,
                          deadline_at=time.monotonic() + 10))

    processed = pump_once(q, max_items=3)
    assert processed == 3
    assert sum(1 for f in futures if f.done()) == 3
    assert q.size == 2


def test_pump_returns_zero_on_empty_queue() -> None:
    q = CommandQueue()
    assert pump_once(q) == 0
