"""Pytest configuration for Pangolin test suite."""
import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "sfr(id): maps test to a Security Functional Requirement")
    # Auto mode lets pytest-asyncio + pytest-aiohttp pick up async test
    # functions + fixtures without per-test decorators (needed for the
    # egress_inspector integration suite).
    config.option.asyncio_mode = "auto"
