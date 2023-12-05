# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for Flask charm database integration."""

import ops
import pytest
from ops.testing import Harness

from xiilib.database_migration import DatabaseMigration, DatabaseMigrationStatus
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
from xiilib.webserver import GunicornWebserver


def test_database_migration(harness: Harness):
    """
    arrange: none
    act: set the database migration script to be different value.
    assert: the restart_flask method will not invoke the database migration script after the
        first successful run.
    """
    harness.begin()
    container: ops.Container = harness.model.unit.get_container(FLASK_CONTAINER_NAME)
    root = harness.get_filesystem_root(FLASK_CONTAINER_NAME)
    harness.set_can_connect(FLASK_CONTAINER_NAME, True)
    charm_state = CharmState(
        flask_secret_key="abc",
        is_secret_storage_ready=True,
        database_migration_script="/flask/app/database-migration.sh",
    )
    webserver = GunicornWebserver(
        charm_state=charm_state,
        container=container,
        service_name=FLASK_SERVICE_NAME,
        app_dir=FLASK_APP_DIR,
        base_dir=FLASK_BASE_DIR,
    )
    database_migration = DatabaseMigration(
        container=container, charm_state=charm_state, state_dir=FLASK_STATE_DIR
    )
    flask_app = FlaskApp(
        charm=harness.charm,
        charm_state=charm_state,
        webserver=webserver,
        database_migration=database_migration,
    )
    database_migration_history = []

    def handle_database_migration(args: ops.testing.ExecArgs):
        """Handle the database migration command."""
        script = args.command[-1]
        database_migration_history.append(script)
        if (root / script.removeprefix("/")).exists():
            return ops.testing.ExecResult(0)
        return ops.testing.ExecResult(1)

    harness.handle_exec(
        FLASK_CONTAINER_NAME, ["/bin/bash", "-xeo", "pipefail"], handler=handle_database_migration
    )
    with pytest.raises(CharmConfigInvalidError):
        flask_app.restart()
    assert database_migration_history == ["/flask/app/database-migration.sh"]

    (root / "flask/app/database-migration.sh").touch()
    flask_app.restart()
    assert database_migration_history == ["/flask/app/database-migration.sh"] * 2

    charm_state.database_migration_script = "database-migration-2.sh"
    flask_app = FlaskApp(
        charm=harness.charm,
        charm_state=charm_state,
        webserver=webserver,
        database_migration=database_migration,
    )
    with pytest.raises(CharmConfigInvalidError):
        flask_app.restart()
    assert database_migration_history == ["/flask/app/database-migration.sh"] * 2


def test_database_migration_rerun(harness: Harness):
    """
    arrange: none
    act: fail the first database migration run and rerun database migration.
    assert: the second database migration run should be successfully.
    """
    harness.begin()
    container: ops.Container = harness.model.unit.get_container(FLASK_CONTAINER_NAME)
    harness.set_can_connect(FLASK_CONTAINER_NAME, True)
    charm_state = CharmState(
        flask_secret_key="abc",
        is_secret_storage_ready=True,
        database_migration_script="/flask/app/database-migration.sh",
    )
    webserver = GunicornWebserver(
        charm_state=charm_state,
        container=container,
        service_name=FLASK_SERVICE_NAME,
        app_dir=FLASK_APP_DIR,
        base_dir=FLASK_BASE_DIR,
    )
    database_migration = DatabaseMigration(
        container=container, charm_state=charm_state, state_dir=FLASK_STATE_DIR
    )
    flask_app = FlaskApp(
        charm=harness.charm,
        charm_state=charm_state,
        database_migration=database_migration,
        webserver=webserver,
    )
    harness.handle_exec(FLASK_CONTAINER_NAME, ["/bin/bash", "-xeo", "pipefail"], result=1)
    with pytest.raises(CharmConfigInvalidError):
        flask_app.restart()
    assert database_migration.get_status() == DatabaseMigrationStatus.FAILED
    harness.handle_exec(FLASK_CONTAINER_NAME, ["/bin/bash", "-xeo", "pipefail"], result=0)
    flask_app.restart()
    assert database_migration.get_status() == DatabaseMigrationStatus.COMPLETED


def test_database_migration_status(harness: Harness):
    """
    arrange: set up the test harness
    act: run the database migration with migration run sets to fail or succeed
    assert: database migration instance should report correct status.
    """
    harness.begin()
    container = harness.charm.unit.get_container(FLASK_CONTAINER_NAME)
    harness.handle_exec(FLASK_CONTAINER_NAME, [], result=1)
    script = "/flask/app/test"
    charm_state = CharmState(database_migration_script=script, is_secret_storage_ready=True)
    database_migration = DatabaseMigration(
        container=container, charm_state=charm_state, state_dir=FLASK_STATE_DIR
    )
    assert database_migration.get_status() == DatabaseMigrationStatus.PENDING
    with pytest.raises(CharmConfigInvalidError):
        database_migration.run({}, FLASK_APP_DIR)
    assert database_migration.get_status() == DatabaseMigrationStatus.FAILED
    harness.handle_exec(FLASK_CONTAINER_NAME, [], result=0)
    database_migration.run({}, FLASK_APP_DIR)
    assert database_migration.get_status() == DatabaseMigrationStatus.COMPLETED
    assert database_migration.get_completed_script() == script
