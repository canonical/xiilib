# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Flask charm database relations unit tests."""

import unittest.mock

import pytest
from ops.testing import Harness

from xiilib.databases import get_uris

DATABASE_URL_TEST_PARAMS = [
    (
        (
            {
                "interface": "mysql",
                "data": {
                    "endpoints": "test-mysql:3306",
                    "password": "test-password",
                    "username": "test-username",
                },
            },
        ),
        {
            "MYSQL_DB_CONNECT_STRING": (
                "mysql://test-username:test-password@test-mysql:3306/flask-app"
            )
        },
    ),
    (
        (
            {
                "interface": "postgresql",
                "data": {
                    "database": "test-database",
                    "endpoints": "test-postgresql:5432,test-postgresql-2:5432",
                    "password": "test-password",
                    "username": "test-username",
                },
            },
        ),
        {
            "POSTGRESQL_DB_CONNECT_STRING": (
                "postgresql://test-username:test-password" "@test-postgresql:5432/test-database"
            )
        },
    ),
    (
        ({"interface": "redis", "data": {"endpoints": "test:6379"}},),
        {"REDIS_DB_CONNECT_STRING": "redis://test:6379"},
    ),
    (
        (
            {
                "interface": "mysql",
                "data": {
                    "endpoints": "test-mysql:3306",
                    "password": "test-password",
                    "username": "test-username",
                },
            },
            {
                "interface": "postgresql",
                "data": {
                    "database": "test-database",
                    "endpoints": "test-postgresql:5432,test-postgresql-2:5432",
                    "password": "test-password",
                    "username": "test-username",
                },
            },
        ),
        {
            "MYSQL_DB_CONNECT_STRING": (
                "mysql://test-username:test-password@test-mysql:3306/flask-app"
            ),
            "POSTGRESQL_DB_CONNECT_STRING": (
                "postgresql://test-username:test-password" "@test-postgresql:5432/test-database"
            ),
        },
    ),
]


@pytest.mark.parametrize("relations, expected_output", DATABASE_URL_TEST_PARAMS)
def test_database_uri_mocked(
    relations: tuple,
    expected_output: dict,
) -> None:
    """
    arrange: none
    act: start the flask charm, set flask-app container to be ready and relate it to the db.
    assert: get_uris() should return the correct databaseURI dict
    """
    # Create the databases mock with the relation data
    _databases = {}
    for relation in relations:
        interface = relation["interface"]
        database_require = unittest.mock.MagicMock()
        database_require.fetch_relation_data = unittest.mock.MagicMock(
            return_value={"data": relation["data"]}
        )
        database_require.database = relation["data"].get("database", "flask-app")
        _databases[interface] = database_require

    assert get_uris(_databases) == expected_output


def test_s3_integrator(harness: Harness, monkeypatch):
    """
    arrange: establish a s3-integrator relation and provide some example data.
    act: retrieve s3 info from charm_state and flask environment.
    assert: s3 connection in charm_state and environment matches example data.
    """
    s3_relation_data = {
        "endpoint": "https://example.com",
        "bucket": "test",
        "region": "us-east-1",
        "data": '{"bucket": "foobar"}',
        "tls-ca-chain": '["test"]',
    }
    s3_info = {
        "endpoint": "https://example.com",
        "bucket": "test",
        "region": "us-east-1",
        "tls-ca-chain": ["test"],
    }
    s3_env = {
        "S3_ENDPOINT": "https://example.com",
        "S3_BUCKET": "test",
        "S3_REGION": "us-east-1",
        "S3_TLS_CA_CHAIN": '["test"]',
    }
    harness.add_relation(
        "s3-credentials",
        "s3-integrator",
        app_data=s3_relation_data,
    )
    harness.begin()
    assert harness.charm._charm_state.s3 == s3_info
    monkeypatch.setattr(harness.charm._charm_state, "_secret_key", "")
    env = harness.charm._wsgi_app._wsgi_environment()
    assert {k: v for k, v in env.items() if k.startswith("S3_")} == s3_env
