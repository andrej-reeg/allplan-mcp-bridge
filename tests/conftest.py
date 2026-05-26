import pytest

from allplan_mcp_server.logging import configure_logging


@pytest.fixture(scope="session", autouse=True)
def _suppress_log_noise() -> None:
    configure_logging(log_level="WARNING")
