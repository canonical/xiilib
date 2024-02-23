#!/usr/bin/env python3
# pylint: disable=duplicate-code

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Flask Charm service."""

import logging
import pathlib
import typing

import ops
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer

from xiilib._gunicorn.charm import CharmMixin
from xiilib._gunicorn.observability import Observability
from xiilib._gunicorn.secret_storage import GunicornSecretStorage
from xiilib._gunicorn.webserver import GunicornWebserver
from xiilib._gunicorn.wsgi_app import WsgiApp
from xiilib.database_migration import DatabaseMigration
from xiilib.databases import Databases, make_database_requirers
from xiilib.exceptions import CharmConfigInvalidError
from xiilib.flask.charm_state import CharmState

logger = logging.getLogger(__name__)


class Charm(ops.CharmBase, CharmMixin):  # pylint: disable=too-many-instance-attributes
    """Flask Charm service."""

    def __init__(self, *args: typing.Any) -> None:
        """Initialize the instance.

        Args:
            args: passthrough to CharmBase.
        """
        super().__init__(*args)
        self._secret_storage = GunicornSecretStorage(charm=self, key="flask_secret_key")
        self._database_requirers = make_database_requirers(self, self.app.name)
        self._s3_requirer = self._create_s3_requirer()

        try:
            self._charm_state = CharmState.from_charm(
                charm=self,
                secret_storage=self._secret_storage,
                database_requirers=self._database_requirers,
                s3_requirer=self._s3_requirer,
            )
        except CharmConfigInvalidError as exc:
            self._update_app_and_unit_status(ops.BlockedStatus(exc.msg))
            return

        self._database_migration = DatabaseMigration(
            container=self.unit.get_container(self._charm_state.container_name),
            state_dir=self._charm_state.state_dir,
        )
        webserver = GunicornWebserver(
            charm_state=self._charm_state,
            container=self.unit.get_container(self._charm_state.container_name),
        )
        self._wsgi_app = WsgiApp(
            charm=self,
            charm_state=self._charm_state,
            webserver=webserver,
            database_migration=self._database_migration,
        )
        self._databases = Databases(
            charm=self,
            application=self._wsgi_app,
            database_requirers=self._database_requirers,
        )
        self._ingress = IngressPerAppRequirer(
            self,
            port=self._charm_state.port,
            strip_prefix=True,
        )
        self._observability = Observability(
            self,
            charm_state=self._charm_state,
            container_name=self._charm_state.container_name,
            cos_dir=str((pathlib.Path(__file__).parent / "cos").absolute()),
        )
        self._observe_default()
        self.framework.observe(self.on.flask_app_pebble_ready, self._on_flask_app_pebble_ready)

    def _on_flask_app_pebble_ready(self, _: ops.PebbleReadyEvent) -> None:
        """Handle the pebble-ready event."""
        self.restart()
