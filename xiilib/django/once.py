# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Provide the DatabaseMigration class to manage database migrations."""
import enum
import json
import logging
import pathlib

import ops

logger = logging.getLogger(__name__)


class RunOnceStatus(str, enum.Enum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PENDING = "PENDING"


class RunOnce:
    def __init__(
        self, charm: ops.CharmBase, container: str, name: str, base_dir: pathlib.Path
    ):
        self._charm = charm
        self._container = self._charm.unit.get_container(container)
        self._name = name
        self._state_dir = base_dir / "state" / "run-once"
        self._state_file = self._state_dir / name
        self._command_archive = self._state_dir / "command"

    def get_status(self) -> RunOnceStatus:
        if not self._container.exists(self._state_file):
            return RunOnceStatus.PENDING
        else:
            return RunOnceStatus(self._container.pull(self._state_file).read())

    def run(
        self, command: list[str], environment: dict[str, str], working_dir: str
    ) -> bool:
        if self.get_status() == RunOnceStatus.COMPLETED:
            return True
        try:
            self._container.make_dir(self._state_dir, make_parents=True)
            proc = self._container.exec(
                command=command, environment=environment, working_dir=working_dir
            )
            stdout, stderr = proc.wait_output()
            logger.info(
                "executed command: %s\nstdout:\n%s\nstderr:\n%s",
                command,
                stdout,
                stderr,
            )
            self._container.push(self._state_file, RunOnceStatus.COMPLETED)
            self._container.push(self._command_archive, json.dumps(command))
            return True
        except ops.pebble.ExecError as exc:
            logger.error(
                "failed to execute command: %s\nstdout:\n%s\nstderr:\n%s",
                command,
                exc.stdout,
                exc.stderr,
            )
            self._container.push(self._state_file, RunOnceStatus.FAILED)
            self._container.push(self._command_archive, json.dumps(command))
            return False
