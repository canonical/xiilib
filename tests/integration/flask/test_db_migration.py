# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for Flask charm database integration."""

import logging

import juju
import requests
from juju.application import Application

logger = logging.getLogger(__name__)


async def test_db_migration(
    flask_db_app: Application,
    model: juju.model.Model,
    get_unit_ips,
):
    """
    arrange: build and deploy the flask charm.
    act: deploy the database and relate it to the charm.
    assert: requesting the charm should return a correct response indicate
        the database migration script has been executed and only executed once.
    """
    db_app = await model.deploy("postgresql-k8s", channel="14/stable", trust=True)
    await model.wait_for_idle()

    await model.add_relation(flask_db_app.name, db_app.name)

    await model.wait_for_idle(status="active")

    for unit_ip in await get_unit_ips(flask_db_app.name):
        assert requests.head(f"http://{unit_ip}:8000/tables/users", timeout=5).status_code == 404

    await flask_db_app.set_config({"database_migration_script": "database-migration.sh"})
    await model.wait_for_idle(status="active")

    for unit_ip in await get_unit_ips(flask_db_app.name):
        assert requests.head(f"http://{unit_ip}:8000/tables/users", timeout=5).status_code == 200
        user_creation_request = {"username": "foo", "password": "bar"}
        response = requests.post(
            f"http://{unit_ip}:8000/users", json=user_creation_request, timeout=5
        )
        assert response.status_code == 201
        response = requests.post(
            f"http://{unit_ip}:8000/users", json=user_creation_request, timeout=5
        )
        assert response.status_code == 400

    await flask_db_app.set_config({"database_migration_script": "database.sh"})
    await model.wait_for_idle()

    assert flask_db_app.status == "blocked"
