# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Flask charm unit tests."""

# this is a unit test file
# pylint: disable=protected-access

import unittest.mock

import yaml
from ops.testing import Harness

from xiilib.flask.charm_state import KNOWN_CHARM_CONFIG, CharmState
from xiilib.flask.constants import (
    FLASK_APP_DIR,
    FLASK_BASE_DIR,
    FLASK_CONTAINER_NAME,
    FLASK_SERVICE_NAME,
)
from xiilib.flask.flask_app import FlaskApp
from xiilib.webserver import GunicornWebserver


def test_flask_pebble_layer(harness: Harness) -> None:
    """
    arrange: none
    act: start the flask charm and set flask-app container to be ready.
    assert: flask charm should submit the correct flaks pebble layer to pebble.
    """
    harness.begin()
    secret_storage = unittest.mock.MagicMock()
    secret_storage.is_initialized = True
    test_key = "0" * 16
    secret_storage.get_flask_secret_key.return_value = test_key
    charm_state = CharmState.from_charm(
        charm=harness.charm, secret_storage=secret_storage, database_uris={}
    )
    webserver = GunicornWebserver(
        charm_state=charm_state,
        container=harness.charm.unit.get_container(FLASK_CONTAINER_NAME),
        service_name=FLASK_SERVICE_NAME,
        app_dir=FLASK_APP_DIR,
        base_dir=FLASK_BASE_DIR,
    )
    flask_app = FlaskApp(
        charm=harness.charm,
        charm_state=charm_state,
        webserver=webserver,
        database_migration=harness.charm._database_migration,
    )
    flask_app.restart()
    plan = harness.get_container_pebble_plan(FLASK_CONTAINER_NAME)
    flask_layer = plan.to_dict()["services"][FLASK_SERVICE_NAME]
    assert flask_layer == {
        "override": "replace",
        "summary": "Flask application service",
        "command": f"python3 -m gunicorn -c {FLASK_BASE_DIR}/gunicorn.conf.py app:app",
        "environment": {"FLASK_PREFERRED_URL_SCHEME": "HTTPS", "FLASK_SECRET_KEY": test_key},
        "startup": "enabled",
    }


def test_known_charm_config():
    """
    arrange: none
    act: none
    assert: KNOWN_CHARM_CONFIG in the consts module matches the content of config.yaml file.
    """
    with open("charmcraft.yaml", encoding="utf-8") as config_file:
        metadata = yaml.safe_load(config_file)
    assert sorted(metadata["config"]["options"].keys()) == sorted(KNOWN_CHARM_CONFIG)


def test_rotate_secret_key_action(harness: Harness):
    """
    arrange: none
    act: invoke the rotate-secret-key callback function
    assert: the action should change the secret key value in the relation data and restart the
        flask application with the new secret key.
    """
    harness.begin_with_initial_hooks()
    action_event = unittest.mock.MagicMock()
    secret_key = harness.get_relation_data(0, harness.charm.app)["flask_secret_key"]
    assert secret_key
    harness.charm._on_rotate_secret_key_action(action_event)
    new_secret_key = harness.get_relation_data(0, harness.charm.app)["flask_secret_key"]
    assert secret_key != new_secret_key
