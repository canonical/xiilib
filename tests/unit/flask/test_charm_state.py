# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Flask charm state unit tests."""
import copy
import unittest.mock

import pytest

from xiilib.exceptions import CharmConfigInvalidError
from xiilib.flask.charm_state import CharmState

# this is a unit test file
# pylint: disable=protected-access

DEFAULT_CHARM_CONFIG = {"webserver_wsgi_path": "app:app", "flask_preferred_url_scheme": "HTTPS"}
SECRET_STORAGE_MOCK = unittest.mock.MagicMock(is_initialized=True)
SECRET_STORAGE_MOCK.get_flask_secret_key.return_value = ""

CHARM_STATE_FLASK_CONFIG_TEST_PARAMS = [
    pytest.param(
        {"flask_env": "prod"}, {"env": "prod", "preferred_url_scheme": "HTTPS"}, id="env"
    ),
    pytest.param(
        {"flask_debug": True}, {"debug": True, "preferred_url_scheme": "HTTPS"}, id="debug"
    ),
    pytest.param(
        {"flask_secret_key": "1234"},
        {"secret_key": "1234", "preferred_url_scheme": "HTTPS"},
        id="secret_key",
    ),
    pytest.param(
        {"flask_preferred_url_scheme": "http"},
        {"preferred_url_scheme": "HTTP"},
        id="preferred_url_scheme",
    ),
]


@pytest.mark.parametrize("charm_config, flask_config", CHARM_STATE_FLASK_CONFIG_TEST_PARAMS)
def test_charm_state_flask_config(charm_config: dict, flask_config: dict) -> None:
    """
    arrange: none
    act: set flask_* charm configurations.
    assert: flask_config in the charm state should reflect changes in charm configurations.
    """
    config = copy.copy(DEFAULT_CHARM_CONFIG)
    config.update(charm_config)
    charm_state = CharmState.from_charm(
        secret_storage=SECRET_STORAGE_MOCK,
        charm=unittest.mock.MagicMock(config=config),
        database_uris={},
    )
    assert charm_state.flask_config == flask_config


@pytest.mark.parametrize(
    "charm_config",
    [
        pytest.param({"flask_env": ""}, id="env"),
        pytest.param({"flask_secret_key": ""}, id="secret_key"),
        pytest.param(
            {"flask_preferred_url_scheme": "tls"},
            id="preferred_url_scheme",
        ),
    ],
)
def test_charm_state_invalid_flask_config(charm_config: dict) -> None:
    """
    arrange: none
    act: set flask_* charm configurations to be invalid values.
    assert: the CharmState should raise a CharmConfigInvalidError exception
    """
    config = copy.copy(DEFAULT_CHARM_CONFIG)
    config.update(charm_config)
    with pytest.raises(CharmConfigInvalidError) as exc:
        CharmState.from_charm(
            secret_storage=SECRET_STORAGE_MOCK,
            charm=unittest.mock.MagicMock(config=config),
            database_uris={},
        )
    for config_key in charm_config:
        assert config_key in exc.value.msg
