#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Flask Charm service."""

import logging
import typing

import ops
from charms.data_platform_libs.v0.data_interfaces import DatabaseRequires, DatabaseRequiresEvent
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer

from xiilib._gunicorn.observability import Observability
from xiilib._gunicorn.wsgi_app import WsgiApp
from xiilib.database_migration import DatabaseMigration, DatabaseMigrationStatus
from xiilib.databases import Databases
from xiilib.exceptions import CharmConfigInvalidError

from .._gunicorn.secret_storage import GunicornSecretStorage
from .charm_state import GunicornCharmState

logger = logging.getLogger(__name__)


class CharmMixin(typing.Protocol):
    """Gunicorn-based charm service mixin."""

    _secret_storage: GunicornSecretStorage
    _charm_state: GunicornCharmState
    _database_migration: DatabaseMigration
    _wsgi_app: WsgiApp
    _database_requirers: dict[str, DatabaseRequires]
    _databases: Databases
    _ingress: IngressPerAppRequirer
    _observability: Observability
    framework: ops.Framework

    @property
    def unit(self) -> ops.Unit:
        """Return the ops charm unit object."""

    @property
    def app(self) -> ops.Application:
        """Typing constrain for the ops.CharmBase class."""

    def _observe_default(self) -> None:
        """Attach all charm event handlers."""
        # can't type this because of the lack of intersection types in Python
        on: ops.CharmEvents = self.on  # type: ignore
        self.framework.observe(on.config_changed, self._on_config_changed)
        self.framework.observe(on.rotate_secret_key_action, self._on_rotate_secret_key_action)
        self.framework.observe(
            on.secret_storage_relation_changed,
            self._on_secret_storage_relation_changed,
        )
        self.framework.observe(on.update_status, self._on_update_status)
        for database, database_requirer in self._database_requirers.items():
            self.framework.observe(
                database_requirer.on.database_created,
                getattr(self, f"_on_{database}_database_database_created"),
            )
            self.framework.observe(
                database_requirer.on.endpoints_changed,
                getattr(self, f"_on_{database}_database_endpoints_changed"),
            )
            self.framework.observe(
                on[database_requirer.relation_name].relation_broken,
                getattr(self, f"_on_{database}_database_relation_broken"),
            )

    def _on_config_changed(self, _event: ops.EventBase) -> None:
        """Configure the flask pebble service layer.

        Args:
            _event: the config-changed event that triggers this callback function.
        """
        self.restart()

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
        self._secret_storage.reset_secret_key()
        event.set_results({"status": "success"})
        self.restart()

    def _on_secret_storage_relation_changed(self, _event: ops.RelationEvent) -> None:
        """Handle the secret-storage-relation-changed event.

        Args:
            _event: the action event that triggers this callback.
        """
        self.restart()

    def _update_app_and_unit_status(self, status: ops.StatusBase) -> None:
        """Update the application and unit status.

        Args:
            status: the desired application and unit status.
        """
        self.unit.status = status
        if self.unit.is_leader():
            self.app.status = status

    def restart(self) -> None:
        """Restart or start the flask service if not started with the latest configuration."""
        try:
            self._wsgi_app.restart()
            self._update_app_and_unit_status(ops.ActiveStatus())
        except CharmConfigInvalidError as exc:
            self._update_app_and_unit_status(ops.BlockedStatus(exc.msg))

    def _on_update_status(self, _: ops.HookEvent) -> None:
        """Handle the update-status event."""
        if self._database_migration.get_status() == DatabaseMigrationStatus.FAILED:
            self.restart()

    def _on_mysql_database_database_created(self, _event: DatabaseRequiresEvent) -> None:
        """Handle the mysql's database-created event."""
        self.restart()

    def _on_mysql_database_endpoints_changed(self, _event: DatabaseRequiresEvent) -> None:
        """Handle the mysql's endpoints-changed event."""
        self.restart()

    def _on_mysql_database_relation_broken(self, _event: ops.RelationBrokenEvent) -> None:
        """Handle the mysql's relation-broken event."""
        self.restart()

    def _on_postgresql_database_database_created(self, _event: DatabaseRequiresEvent) -> None:
        """Handle the postgresql's database-created event."""
        self.restart()

    def _on_postgresql_database_endpoints_changed(self, _event: DatabaseRequiresEvent) -> None:
        """Handle the mysql's endpoints-changed event."""
        self.restart()

    def _on_postgresql_database_relation_broken(self, _event: ops.RelationBrokenEvent) -> None:
        """Handle the postgresql's relation-broken event."""
        self.restart()
