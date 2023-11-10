# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Provide the DatabaseMigration class to manage database migrations."""
import enum
import logging
import pathlib
import typing
from typing import cast

import ops
from ops.pebble import ExecError

from xiilib.exceptions import CharmConfigInvalidError

logger = logging.getLogger(__name__)


class DatabaseMigrationStatus(str, enum.Enum):
    """Database migration status.

    Attrs:
        COMPLETED: A status denoting a successful database migration.
        FAILED: A status denoting an unsuccessful database migration.
        PENDING: A status denoting a pending database migration.
    """

    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PENDING = "PENDING"


class DatabaseMigrationCharmState(typing.Protocol):  # pylint: disable=too-few-public-methods
    """Charm state required for DatabaseMigration class.

    Attrs:
        database_migration_script: the database migration configuration, None for unset.
    """

    @property
    def database_migration_script(self) -> str | None:
        """Return the database migration script configuration.

        Returns:
            the database migration configuration, None for unset.
        """


class DatabaseMigration:
    """The DatabaseMigration class that manages database migrations.

    Attrs:
        script: the database migration script.
    """

    def __init__(
        self,
        container: ops.Container,
        charm_state: DatabaseMigrationCharmState,
        state_dir: pathlib.Path,
    ):
        """Initialize the DatabaseMigration instance.

        Args:
            container: The application container object.
            charm_state: The charm state.
            state_dir: the directory in the application container to store migration states.
        """
        self._container = container
        self._charm_state = charm_state
        self._status_file = state_dir / "database-migration-status"
        self._completed_script_file = state_dir / "completed-database-migration"

    @property
    def script(self) -> str | None:
        """Get the database migration script."""
        return self._charm_state.database_migration_script

    def get_status(self) -> DatabaseMigrationStatus:
        """Get the database migration run status.

        Returns:
            One of "PENDING", "COMPLETED", or "FAILED".
        """
        return (
            DatabaseMigrationStatus.PENDING
            if not self._container.exists(self._status_file)
            else DatabaseMigrationStatus(cast(str, self._container.pull(self._status_file).read()))
        )

    def _set_status(self, status: DatabaseMigrationStatus) -> None:
        """Set the database migration run status.

        Args:
            status: One of "PENDING", "COMPLETED", or "FAILED".
        """
        self._container.push(self._status_file, source=status, make_dirs=True)

    def get_completed_script(self) -> str | None:
        """Get the database migration script that has completed in the current container.

        Returns:
            The completed database migration script in the current container.
        """
        if self._container.exists(self._completed_script_file):
            return cast(str, self._container.pull(self._completed_script_file).read())
        return None

    def _set_completed_script(self, script_path: str) -> None:
        """Set the database migration script that has completed in the current container.

        Args:
            script_path: The completed database migration script in the current container.
        """
        self._container.push(self._completed_script_file, script_path, make_dirs=True)

    def run(self, environment: dict[str, str], working_dir: pathlib.Path) -> None:
        """Run the database migration script if database migration is still pending.

        Args:
            environment: Environment variables that's required for the run.
            working_dir: Working directory for the database migration run.

        Raises:
            CharmConfigInvalidError: if the database migration run failed.
        """
        if self.get_status() not in (
            DatabaseMigrationStatus.PENDING,
            DatabaseMigrationStatus.FAILED,
        ):
            return
        if not self.script:
            return
        logger.info("execute database migration script: %s", repr(self.script))
        try:
            self._container.exec(
                ["/bin/bash", "-xeo", "pipefail", self.script],
                environment=environment,
                working_dir=str(working_dir),
            ).wait_output()
            self._set_status(DatabaseMigrationStatus.COMPLETED)
            self._set_completed_script(self.script)
        except ExecError as exc:
            self._set_status(DatabaseMigrationStatus.FAILED)
            logger.error(
                "database migration script %s failed, stdout: %s, stderr: %s",
                repr(self.script),
                exc.stdout,
                exc.stderr,
            )
            raise CharmConfigInvalidError(
                f"database migration script {self.script!r} failed, "
                "will retry in next update-status"
            ) from exc
