#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Django Charm service."""
import json
import pathlib
import secrets

import ops
from ops import ActiveStatus
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer

from .databases import Databases, DatabasesEvents
from .once import RunOnce, RunOnceStatus
from .server import GunicornServer, WebserverError
from .observability import Observability
from .secret_storage import SecretStorage


class Charm(ops.CharmBase):
    _CONTAINER_NAME = "django-app"
    _BASE_DIR = pathlib.Path("/django")
    _SECRET_KEY_SECRET_STORAGE_KEY = "django_secret_key"

    def __init__(self, *args):
        super().__init__(*args)
        self._databases = Databases(charm=self, database_name=self.app.name)
        self._database_migration = RunOnce(
            charm=self,
            container=self._CONTAINER_NAME,
            name="database-migration",
            base_dir=self._BASE_DIR,
        )
        self._server = GunicornServer(
            charm=self, container=self._CONTAINER_NAME, base_dir=self._BASE_DIR
        )
        self._observability = Observability(
            charm=self,
            container=self._CONTAINER_NAME,
            cos_dir=pathlib.Path(__file__).parent.absolute() / "cos",
            log_files=[self._server.access_log, self._server.error_log],
            metrics_port=9102,
        )
        self._secrets = SecretStorage(
            charm=self,
            initial_values={
                self._SECRET_KEY_SECRET_STORAGE_KEY: secrets.token_urlsafe(32)
            },
        )
        self._ingress = IngressPerAppRequirer(
            self,
            port=self._server.port,
            strip_prefix=True,
        )
        self.framework.observe(self.on.upgrade_charm, self._on_upgrade_charm)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(
            self.on.rotate_secret_key_action, self._on_rotate_secret_key_action
        )
        self.framework.observe(
            self.on.secret_storage_relation_changed,
            self._on_secret_storage_relation_changed,
        )
        self.framework.observe(
            self.on.django_app_pebble_ready, self._on_django_app_pebble_ready
        )
        self.framework.observe(self.on.update_status, self._on_update_status)
        self.framework.observe(
            self._databases.on.all_databases_ready, self._on_all_databases_ready
        )

    def _get_environment(self) -> dict[str, str]:
        env = self._databases.get_uris()
        allowed_hosts = self.config.get("django_allowed_hosts")
        if allowed_hosts:
            env["DJANGO_ALLOWED_HOSTS"] = json.dumps(
                [h.strip() for h in allowed_hosts.split(",") if h.strip()]
            )
        secret_key = self.config.get("django_secret_key")
        if not secret_key:
            secret_key = self._secrets.get_secret(self._SECRET_KEY_SECRET_STORAGE_KEY)
        env["DJANGO_SECRET_KEY"] = json.dumps(secret_key)
        return env

    def reconcile(self):
        container = self.unit.get_container(self._CONTAINER_NAME)
        if not container.can_connect():
            self.unit.status = ops.WaitingStatus("Waiting for pebble ready")
            return

        if not self._databases.is_ready():
            status = ops.WaitingStatus("Waiting for database integrations")
            self.unit.status = status
            if self.unit.is_leader():
                self.app.status = status
            return

        if not self._secrets.is_initialized:
            self.unit.status = ops.WaitingStatus(
                "Waiting for secret store initialization"
            )
            return

        if self._databases.get_uris():
            status = self.unit.status
            self.unit.status = ops.MaintenanceStatus("Executing database migration")
            migration_ok = self._database_migration.run(
                ["python3", "manage.py", "migrate"],
                environment=self._get_environment(),
                working_dir=str(self._BASE_DIR / "app"),
            )
            self.unit.status = status
            if not migration_ok:
                self.unit.status = ops.BlockedStatus(
                    "Database migration failed, will retry in the next update-status"
                )
                return

        try:
            self._server.apply(self._get_environment())
            self.unit.status = ActiveStatus()
            if self.unit.is_leader():
                self.app.status = ActiveStatus()
        except WebserverError:
            self.unit.status = ops.BlockedStatus(
                "Webserver start-up failed, review your charm config or database relation"
            )

    def _on_upgrade_charm(self, _event: ops.UpgradeCharmEvent):
        self.reconcile()

    def _on_config_changed(self, _event: ops.ConfigChangedEvent):
        self.reconcile()

    def _on_rotate_secret_key_action(self, event: ops.ActionEvent) -> None:
        """Handle the rotate-secret-key action.

        Args:
            event: the action event that trigger this callback.
        """
        if not self.unit.is_leader():
            event.fail("only leader unit can rotate secret key")
            return
        if not self._secrets.is_initialized:
            event.fail("charm is still initializing")
            return
        self._secrets.set_secret(
            self._SECRET_KEY_SECRET_STORAGE_KEY, secrets.token_urlsafe(32)
        )
        event.set_results({"status": "success"})
        self.reconcile()

    def _on_secret_storage_relation_changed(self, _event: ops.RelationEvent) -> None:
        """Handle the secret-storage-relation-changed event."""
        self.reconcile()

    def _on_update_status(self, _event: ops.HookEvent) -> None:
        """Handle the update-status event."""
        if self._database_migration.get_status() == RunOnceStatus.FAILED:
            self.reconcile()

    def _on_django_app_pebble_ready(self, _event: ops.PebbleReadyEvent) -> None:
        """Handle the pebble-ready event."""
        self.reconcile()

    def _on_all_databases_ready(self, _event: DatabasesEvents):
        self.reconcile()
