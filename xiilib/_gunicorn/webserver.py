# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Provide the GunicornWebserver class to represent the gunicorn server."""
import dataclasses
import datetime
import logging
import pathlib
import shlex
import signal
import typing

import ops
from ops.pebble import ExecError, PathError

from xiilib.exceptions import CharmConfigInvalidError

if typing.TYPE_CHECKING:
    from xiilib._gunicorn.charm_state import CharmState

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class WebserverConfig:
    """Represent the configuration values for a web server.

    Attributes:
        workers: The number of workers to use for the web server, or None if not specified.
        threads: The number of threads per worker to use for the web server,
            or None if not specified.
        keepalive: The time to wait for requests on a Keep-Alive connection,
            or None if not specified.
        timeout: The request silence timeout for the web server, or None if not specified.
    """

    workers: int | None = None
    threads: int | None = None
    keepalive: datetime.timedelta | None = None
    timeout: datetime.timedelta | None = None

    def items(self) -> typing.Iterable[tuple[str, int | datetime.timedelta | None]]:
        """Return the dataclass values as an iterable of the key-value pairs.

        Returns:
            An iterable of the key-value pairs.
        """
        return {
            "workers": self.workers,
            "threads": self.threads,
            "keepalive": self.keepalive,
            "timeout": self.timeout,
        }.items()

    @classmethod
    def from_charm(cls, charm: ops.CharmBase) -> "WebserverConfig":
        """Create a WebserverConfig object from a charm object.

        Args:
            charm: The charm object.

        Returns:
            A WebserverConfig object.
        """
        keepalive = charm.config.get("webserver-keepalive")
        timeout = charm.config.get("webserver-timeout")
        workers = charm.config.get("webserver-workers")
        threads = charm.config.get("webserver-threads")
        return cls(
            workers=int(typing.cast(str, workers)) if workers is not None else None,
            threads=int(typing.cast(str, threads)) if threads is not None else None,
            keepalive=(
                datetime.timedelta(seconds=int(keepalive)) if keepalive is not None else None
            ),
            timeout=(datetime.timedelta(seconds=int(timeout)) if timeout is not None else None),
        )


class GunicornWebserver:  # pylint: disable=too-few-public-methods
    """A class representing a Gunicorn web server."""

    def __init__(
        self,
        charm_state: "CharmState",
        container: ops.Container,
    ):
        """Initialize a new instance of the GunicornWebserver class.

        Args:
            charm_state: The state of the charm that the GunicornWebserver instance belongs to.
            container: The WSGI application container in this charm unit.
        """
        self._charm_state = charm_state
        self._container = container
        self._reload_signal = signal.SIGHUP

    @property
    def _config(self) -> str:
        """Generate the content of the Gunicorn configuration file based on charm states.

        Returns:
            The content of the Gunicorn configuration file.
        """
        config_entries = []
        for setting, setting_value in self._charm_state.webserver_config.items():
            setting_value = typing.cast(None | int | datetime.timedelta, setting_value)
            if setting_value is None:
                continue
            setting_value = (
                setting_value
                if isinstance(setting_value, int)
                else int(setting_value.total_seconds())
            )
            config_entries.append(f"{setting} = {setting_value}")
        new_line = "\n"
        config = f"""\
bind = ['0.0.0.0:{self._charm_state.port}']
chdir = {repr(str(self._charm_state.app_dir))}
accesslog = {repr(str(self._charm_state.application_log_file.absolute()))}
errorlog = {repr(str(self._charm_state.application_error_log_file.absolute()))}
statsd_host = {repr(self._charm_state.statsd_host)}
{new_line.join(config_entries)}"""
        return config

    @property
    def _config_path(self) -> pathlib.Path:
        """Gets the path to the Gunicorn configuration file.

        Returns:
            The path to the web server configuration file.
        """
        return self._charm_state.base_dir / "gunicorn.conf.py"

    def update_config(
        self, environment: dict[str, str], is_webserver_running: bool, command: str
    ) -> None:
        """Update and apply the configuration file of the web server.

        Args:
            environment: Environment variables used to run the application.
            is_webserver_running: Indicates if the web server container is currently running.
            command: The WSGI application startup command.

        Raises:
            CharmConfigInvalidError: if the charm configuration is not valid.
        """
        self._prepare_log_dir()
        webserver_config_path = str(self._config_path)
        try:
            current_webserver_config = self._container.pull(webserver_config_path)
        except PathError:
            current_webserver_config = None
        self._container.push(webserver_config_path, self._config)
        if current_webserver_config == self._config:
            return
        check_config_command = shlex.split(command)
        check_config_command.append("--check-config")
        exec_process = self._container.exec(
            check_config_command,
            environment=environment,
            user=self._charm_state.user,
            group=self._charm_state.group,
            working_dir=str(self._charm_state.app_dir),
        )
        try:
            exec_process.wait_output()
        except ExecError as exc:
            logger.error(
                "webserver configuration check failed, stdout: %s, stderr: %s",
                exc.stdout,
                exc.stderr,
            )
            raise CharmConfigInvalidError(
                "Webserver configuration check failed, "
                "please review your charm configuration or database relation"
            ) from exc
        if is_webserver_running:
            logger.info("gunicorn config changed, reloading")
            self._container.send_signal(self._reload_signal, self._charm_state.service_name)

    def _prepare_log_dir(self) -> None:
        """Prepare access and error log directory for the application."""
        container = self._container
        for log in (
            self._charm_state.application_log_file,
            self._charm_state.application_error_log_file,
        ):
            log_dir = str(log.parent.absolute())
            if not container.exists(log_dir):
                container.make_dir(
                    log_dir,
                    make_parents=True,
                    user=self._charm_state.user,
                    group=self._charm_state.group,
                )
