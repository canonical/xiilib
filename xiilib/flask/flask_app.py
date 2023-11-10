# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Provide the FlaskApp class to represent the Flask application."""
import json
import logging
import shlex

import ops

from xiilib.flask.charm_state import KNOWN_CHARM_CONFIG, CharmState
from xiilib.flask.constants import FLASK_APP_DIR, FLASK_ENV_CONFIG_PREFIX, FLASK_SERVICE_NAME
from xiilib.exceptions import CharmConfigInvalidError
from xiilib.database_migration import DatabaseMigration
from xiilib.webserver import GunicornWebserver

logger = logging.getLogger(__name__)


class FlaskApp:  # pylint: disable=too-few-public-methods
    """Flask application manager."""

    def __init__(
        self,
        charm: ops.CharmBase,
        charm_state: CharmState,
        webserver: GunicornWebserver,
        database_migration: DatabaseMigration,
    ):
        """Construct the FlaskApp instance.

        Args:
            charm: The main charm object.
            charm_state: The state of the charm.
            webserver: The webserver manager object.
            database_migration: The database migration manager object.
        """
        self._charm = charm
        self._charm_state = charm_state
        self._webserver = webserver
        self._database_migration = database_migration

    def _flask_environment(self) -> dict[str, str]:
        """Generate a Flask environment dictionary from the charm Flask configurations.

        The Flask environment generation follows these rules:
            1. User-defined configuration cannot overwrite built-in Flask configurations, even if
                the built-in Flask configuration value is None (undefined).
            2. Boolean and integer-typed configuration values will be JSON encoded before
                being passed to Flask.
            3. String-typed configuration values will be passed to Flask as environment variables
                directly.

        Returns:
            A dictionary representing the Flask environment variables.
        """
        builtin_flask_config = [
            c.removeprefix("flask_") for c in KNOWN_CHARM_CONFIG if c.startswith("flask_")
        ]
        flask_env = {
            k: v for k, v in self._charm_state.app_config.items() if k not in builtin_flask_config
        }
        flask_env.update(self._charm_state.flask_config)
        env = {
            f"{FLASK_ENV_CONFIG_PREFIX}{k.upper()}": v if isinstance(v, str) else json.dumps(v)
            for k, v in flask_env.items()
        }
        secret_key_env = f"{FLASK_ENV_CONFIG_PREFIX}SECRET_KEY"
        if secret_key_env not in env:
            env[secret_key_env] = self._charm_state.flask_secret_key
        for proxy_variable in ("http_proxy", "https_proxy", "no_proxy"):
            proxy_value = getattr(self._charm_state.proxy, proxy_variable)
            if proxy_value:
                env[proxy_variable] = str(proxy_value)
                env[proxy_variable.upper()] = str(proxy_value)
        env.update(self._charm_state.database_uris)
        return env

    def _flask_layer(self) -> ops.pebble.LayerDict:
        """Generate the pebble layer definition for flask application.

        Returns:
            The pebble layer definition for flask application.
        """
        environment = self._flask_environment()
        return ops.pebble.LayerDict(
            services={
                FLASK_SERVICE_NAME: {
                    "override": "replace",
                    "summary": "Flask application service",
                    "command": shlex.join(self._webserver.command),
                    "startup": "enabled",
                    "environment": environment,
                }
            },
        )

    def restart(self) -> None:
        """Restart or start the flask service if not started with the latest configuration.

        Raises:
             CharmConfigInvalidError: if the configuration is not valid.
        """
        container = self._charm.unit.get_container("flask-app")
        if not container.can_connect():
            logger.info("pebble client in the Flask container is not ready")
            return
        if not self._charm_state.is_secret_storage_ready:
            logger.info("secret storage is not initialized")
            return
        container.add_layer("flask", self._flask_layer(), combine=True)
        is_webserver_running = container.get_service(FLASK_SERVICE_NAME).is_running()
        self._webserver.update_config(
            environment=self._flask_environment(),
            is_webserver_running=is_webserver_running,
        )
        self._database_migration.run(self._flask_environment(), working_dir=FLASK_APP_DIR)
        container.replan()
        if (
            self._database_migration.get_completed_script() is not None
            and self._database_migration.script is not None
            and self._database_migration.script != self._database_migration.get_completed_script()
        ):
            raise CharmConfigInvalidError(
                f"database migration script {self._database_migration.get_completed_script()!r} "
                f"has been executed successfully in the current flask container,"
                f"updating database-migration-script in config has no effect"
            )
