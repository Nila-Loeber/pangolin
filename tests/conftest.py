"""Pytest configuration for Pangolin test suite."""
import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "sfr(id): maps test to a Security Functional Requirement")
