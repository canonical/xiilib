# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Global fixtures and utilities for integration and unit tests."""


def pytest_addoption(parser):
    """Define some command line options for integration and unit tests."""
    parser.addoption("--charm-file", action="store")
    parser.addoption("--flask-app-image", action="store")
    parser.addoption("--test-flask-image", action="store")
    parser.addoption("--test-db-flask-image", action="store")
