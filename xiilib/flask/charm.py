#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Flask Charm service."""

import logging
import pathlib
import textwrap
import typing

import ops
from charms.data_platform_libs.v0.data_interfaces import DatabaseRequiresEvent
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer

from xiilib.database_migration import DatabaseMigration, DatabaseMigrationStatus
from xiilib.databases import Databases, get_uris, make_database_requirers
from xiilib.exceptions import CharmConfigInvalidError
from xiilib.flask.charm_state import CharmState
from xiilib.flask.constants import (
    FLASK_APP_DIR,
    FLASK_BASE_DIR,
    FLASK_CONTAINER_NAME,
    FLASK_SERVICE_NAME,
    FLASK_STATE_DIR,
)
from xiilib.flask.flask_app import FlaskApp
from xiilib.flask.secret_storage import FlaskSecretStorage
from xiilib.observability import Observability
from xiilib.webserver import GunicornWebserver

logger = logging.getLogger(__name__)


class Charm(ops.CharmBase):  # pylint: disable=too-many-instance-attributes
    """Flask Charm service."""

    def __init__(self, *args: typing.Any) -> None:
        """Initialize the instance.

        Args:
            args: passthrough to CharmBase.
        """
        super().__init__(*args)
        self.okay = True
        self._secret_storage = FlaskSecretStorage(charm=self)
        database_requirers = make_database_requirers(self, "flask-app")

        try:
            self._charm_state = CharmState.from_charm(
                charm=self,
                secret_storage=self._secret_storage,
                database_uris=get_uris(database_requirers),
            )
        except CharmConfigInvalidError as exc:
            self._update_app_and_unit_status(ops.BlockedStatus(exc.msg))
            return

        self._database_migration = DatabaseMigration(
            container=self.unit.get_container(FLASK_CONTAINER_NAME),
            charm_state=self._charm_state,
            state_dir=FLASK_STATE_DIR,
        )
        webserver = GunicornWebserver(
            charm_state=self._charm_state,
            container=self.unit.get_container(FLASK_CONTAINER_NAME),
            service_name=FLASK_SERVICE_NAME,
            app_dir=FLASK_APP_DIR,
            base_dir=FLASK_BASE_DIR,
        )
        self._flask_app = FlaskApp(
            charm=self,
            charm_state=self._charm_state,
            webserver=webserver,
            database_migration=self._database_migration,
        )
        self._databases = Databases(
            charm=self,
            application=self._flask_app,
            database_requirers=database_requirers,
        )
        self._ingress = IngressPerAppRequirer(
            self,
            port=self._charm_state.port,
            strip_prefix=True,
        )
        self._observability = Observability(
            self,
            charm_state=self._charm_state,
            container_name=FLASK_CONTAINER_NAME,
            cos_dir=str((pathlib.Path(__file__).parent / "cos").absolute()),
        )
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.rotate_secret_key_action, self._on_rotate_secret_key_action)
        self.framework.observe(
            self.on.secret_storage_relation_changed,
            self._on_secret_storage_relation_changed,
        )
        self.framework.observe(self.on.flask_app_pebble_ready, self._on_flask_app_pebble_ready)
        self.framework.observe(self.on.update_status, self._on_update_status)
        self.framework.observe(
            self.on.statsd_prometheus_exporter_pebble_ready,
            self._on_statsd_prometheus_exporter_pebble_ready,
        )
        for database, database_requirer in database_requirers.items():
            self.framework.observe(
                database_requirer.on.database_created,
                getattr(self, f"_on_{database}_database_database_created"),
            )
            self.framework.observe(
                self.on[database_requirer.relation_name].relation_broken,
                getattr(self, f"_on_{database}_database_relation_broken"),
            )

    def _on_config_changed(self, _event: ops.EventBase) -> None:
        """Configure the flask pebble service layer.

        Args:
            _event: the config-changed event that triggers this callback function.
        """
        self._restart_flask()

    def _on_rotate_secret_key_action(self, event: ops.ActionEvent) -> None:
        """Handle the rotate-secret-key action.

        Args:
            event: the action event that trigger this callback.
        """
        if not self.unit.is_leader():
            event.fail("only leader unit can rotate secret key")
            return
        if not self._secret_storage.is_initialized:
            event.fail("flask charm is still initializing")
            return
        self._secret_storage.reset_flask_secret_key()
        event.set_results({"status": "success"})
        self._restart_flask()

    def _on_secret_storage_relation_changed(self, _event: ops.RelationEvent) -> None:
        """Handle the secret-storage-relation-changed event.

        Args:
            _event: the action event that triggers this callback.
        """
        self._restart_flask()

    def _update_app_and_unit_status(self, status: ops.StatusBase) -> None:
        """Update the application and unit status.

        Args:
            status: the desired application and unit status.
        """
        self.unit.status = status
        if self.unit.is_leader():
            self.app.status = status

    def _restart_flask(self) -> None:
        """Restart or start the flask service if not started with the latest configuration."""
        try:
            self._flask_app.restart()
            self._update_app_and_unit_status(ops.ActiveStatus())
        except CharmConfigInvalidError as exc:
            self._update_app_and_unit_status(ops.BlockedStatus(exc.msg))

    def _on_update_status(self, _: ops.HookEvent) -> None:
        """Handle the update-status event."""
        if self._database_migration.get_status() == DatabaseMigrationStatus.FAILED:
            self._restart_flask()

    def _on_flask_app_pebble_ready(self, _: ops.PebbleReadyEvent) -> None:
        """Handle the pebble-ready event."""
        self._restart_flask()

    def _on_statsd_prometheus_exporter_pebble_ready(self, _event: ops.PebbleReadyEvent) -> None:
        """Handle the statsd-prometheus-exporter-pebble-ready event."""
        container = self.unit.get_container("statsd-prometheus-exporter")
        container.push(
            "/statsd.conf",
            textwrap.dedent(
                """\
                mappings:
                  - match: gunicorn.request.status.*
                    name: flask_response_code
                    labels:
                      status: $1
                  - match: gunicorn.requests
                    name: flask_requests
                  - match: gunicorn.request.duration
                    name: flask_request_duration
                """
            ),
        )
        statsd_layer = ops.pebble.LayerDict(
            summary="statsd exporter layer",
            description="statsd exporter layer",
            services={
                "statsd-prometheus-exporter": {
                    "override": "replace",
                    "summary": "statsd exporter service",
                    "user": "nobody",
                    "command": "/bin/statsd_exporter --statsd.mapping-config=/statsd.conf",
                    "startup": "enabled",
                }
            },
            checks={
                "container-ready": {
                    "override": "replace",
                    "level": "ready",
                    "http": {"url": "http://localhost:9102/metrics"},
                },
            },
        )
        container.add_layer("statsd-prometheus-exporter", statsd_layer, combine=True)
        container.replan()

    def _on_mysql_database_database_created(self, _event: DatabaseRequiresEvent) -> None:
        """Handle the mysql's database-created event."""
        self._restart_flask()

    def _on_mysql_database_relation_broken(self, _event: ops.RelationBrokenEvent) -> None:
        """Handle the mysql's relation-broken event."""
        self._restart_flask()

    def _on_postgresql_database_database_created(self, _event: DatabaseRequiresEvent) -> None:
        """Handle the postgresql's database-created event."""
        self._restart_flask()

    def _on_postgresql_database_relation_broken(self, _event: ops.RelationBrokenEvent) -> None:
        """Handle the postgresql's relation-broken event."""
        self._restart_flask()
