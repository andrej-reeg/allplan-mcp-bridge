"""Tests for allplan_agent/command_queue.py — threading safety."""

import threading
import time
from concurrent.futures import Future
from typing import Any

import pytest

from allplan_agent.command_queue import Command, CommandQueue, QueueFullError


def _make_cmd(cmd_id: str, deadline_offset: float = 10.0) -> Command:
    fut: Future[dict[str, Any]] = Future()
    return Command(
        id=cmd_id,
        cmd_name="noop",
        args={},
        future=fut,
        deadline_at=time.monotonic() + deadline_offset,
    )


# --- basic operations ---

def test_enqueue_and_drain_single() -> None:
    q = CommandQueue()
    cmd = _make_cmd("1")
    q.enqueue(cmd)
    drained = q.drain()
    assert len(drained) == 1
    assert drained[0].id == "1"


def test_drain_empty_returns_empty() -> None:
    q = CommandQueue()
    assert q.drain() == []


def test_drain_respects_max_items() -> None:
    q = CommandQueue()
    for i in range(10):
        q.enqueue(_make_cmd(str(i)))
    drained = q.drain(max_items=3)
    assert len(drained) == 3
    assert q.size == 7


def test_queue_full_raises() -> None:
    q = CommandQueue(maxsize=2)
    q.enqueue(_make_cmd("a"))
    q.enqueue(_make_cmd("b"))
    with pytest.raises(QueueFullError):
        q.enqueue(_make_cmd("c"))


def test_size_reflects_queue_depth() -> None:
    q = CommandQueue()
    assert q.size == 0
    q.enqueue(_make_cmd("x"))
    assert q.size == 1
    q.drain()
    assert q.size == 0


# --- threading safety ---

def test_concurrent_enqueue_1000() -> None:
    """1000 commands from N threads all land in the queue exactly once."""
    q = CommandQueue(maxsize=2000)
    n_threads = 10
    cmds_per_thread = 100
    errors: list[Exception] = []

    def _enqueue(thread_id: int) -> None:
        for i in range(cmds_per_thread):
            try:
                q.enqueue(_make_cmd(f"{thread_id}-{i}"))
            except Exception as exc:
                errors.append(exc)

    threads = [threading.Thread(target=_enqueue, args=(t,)) for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    total = 0
    while True:
        batch = q.drain(max_items=50)
        if not batch:
            break
        total += len(batch)
    assert total == n_threads * cmds_per_thread


def test_concurrent_enqueue_drain_no_lost_commands() -> None:
    """Simultaneous enqueue and drain: no commands lost, no duplicates."""
    q = CommandQueue(maxsize=1000)
    produced: list[str] = []
    consumed: list[str] = []
    lock = threading.Lock()
    done = threading.Event()

    def _producer() -> None:
        for i in range(200):
            cmd = _make_cmd(f"p-{i}")
            with lock:
                produced.append(cmd.id)
            q.enqueue(cmd)

    def _drainer() -> None:
        while not done.is_set() or q.size > 0:
            for cmd in q.drain(max_items=10):
                with lock:
                    consumed.append(cmd.id)
            time.sleep(0.001)

    drainer = threading.Thread(target=_drainer)
    drainer.start()
    producers = [threading.Thread(target=_producer) for _ in range(3)]
    for p in producers:
        p.start()
    for p in producers:
        p.join()
    # give drainer time to finish
    time.sleep(0.05)
    done.set()
    drainer.join()

    assert sorted(consumed) == sorted(produced)


def test_make_command_convenience() -> None:
    q = CommandQueue()
    cmd, fut = q.make_command("id-1", "create_wall", {"x": 1}, timeout_seconds=5.0)
    assert cmd.id == "id-1"
    assert cmd.cmd_name == "create_wall"
    assert isinstance(fut, Future)
    assert cmd.future is fut
    assert cmd.deadline_at > time.monotonic()
