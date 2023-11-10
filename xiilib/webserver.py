# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Provide the GunicornWebserver class to represent the gunicorn server."""
import datetime
import logging
import pathlib
import signal
import typing

import ops
from ops.pebble import ExecError, PathError

from xiilib.exceptions import CharmConfigInvalidError

logger = logging.getLogger(__name__)


class WebserverConfig(typing.TypedDict):
    """Represent the configuration values for a web server.

    Attributes:
        workers: The number of workers to use for the web server, or None if not specified.
        threads: The number of threads per worker to use for the web server,
            or None if not specified.
        keepalive: The time to wait for requests on a Keep-Alive connection,
            or None if not specified.
        timeout: The request silence timeout for the web server, or None if not specified.
    """

    workers: int | None
    threads: int | None
    keepalive: datetime.timedelta | None
    timeout: datetime.timedelta | None


class WSGICharmState(typing.Protocol):
    """Charm state for WSGI applications.

    Attrs:
        application_log_file: the path to the application's main log file.
        application_error_log_file: the path to the application's error file.
        port: the port number to use for the WSGI server.
        webserver_config: the web server configuration file content for the charm.
    """

    @property
    def application_log_file(self) -> pathlib.Path:
        """Return the path to the application's main log file.

        Returns:
            The path to the application's main log file.
        """

    @property
    def application_error_log_file(self) -> pathlib.Path:
        """Return the path to the application's error log file.

        Returns:
            The path to the application's error log file.
        """

    @property
    def port(self) -> int:
        """Gets the port number to use for the WSGI server.

        Returns:
            The port number to use for the WSGI server.
        """
        return 8000

    @property
    def webserver_config(self) -> WebserverConfig:
        """Get the web server configuration file content for the charm.

        Returns:
            The web server configuration file content for the charm.
        """


class GunicornCharmState(WSGICharmState, typing.Protocol):
    """Charm state required by the Gunicorn class.

    Attrs:
        statsd_host: the statsd server host for gunicorn metrics
    """

    @property
    def statsd_host(self) -> str:
        """Returns the statsd server host for gunicorn metrics.

        Returns:
            The statsd server host for gunicorn metrics.
        """


class GunicornWebserver:
    """A class representing a Gunicorn web server.

    Attrs:
        command: the command to start the Gunicorn web server.

    """

    def __init__(
        self,
        charm_state: GunicornCharmState,
        container: ops.Container,
        service_name: str,
        base_dir: pathlib.Path,
        app_dir: pathlib.Path,
    ):
        """Initialize a new instance of the GunicornWebserver class.

        Args:
            charm_state: The state of the charm that the GunicornWebserver instance belongs to.
            container: The WSGI application container in this charm unit.
            service_name: The WSGI application pebble service name.
            base_dir: The project base directory in the WSGI application container.
            app_dir: The WSGI application directory in the WSGI application container.
        """
        self._charm_state = charm_state
        self._container = container
        self._service_name = service_name
        self._base_dir = base_dir
        self._app_dir = app_dir

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
chdir = {repr(str(self._app_dir))}
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
        return self._base_dir / "gunicorn.conf.py"

    @property
    def command(self) -> list[str]:
        """Get the command to start the Gunicorn web server.

        Returns:
            The command to start the Gunicorn web server.
        """
        return [
            "python3",
            "-m",
            "gunicorn",
            "-c",
            str(self._config_path),
            "app:app",
        ]

    @property
    def _check_config_command(self) -> list[str]:
        """Returns the command to check the Gunicorn configuration.

        Returns:
            The command to check the Gunicorn configuration.
        """
        return self.command + ["--check-config"]

    @property
    def _reload_signal(self) -> signal.Signals:
        """Get the signal used to reload the Gunicorn web server.

        Returns:
            The signal used to reload the Gunicorn web server.
        """
        return signal.SIGHUP

    def update_config(self, environment: dict[str, str], is_webserver_running: bool) -> None:
        """Update and apply the configuration file of the web server.

        Args:
            environment: Environment variables used to run the application.
            is_webserver_running: Indicates if the web server container is currently running.

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
        exec_process = self._container.exec(
            self._check_config_command, environment=environment
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
            self._container.send_signal(self._reload_signal, self._service_name)

    def _prepare_log_dir(self) -> None:
        """Prepare access and error log directory for the application."""
        container = self._container
        for log in (
            self._charm_state.application_log_file,
            self._charm_state.application_error_log_file,
        ):
            log_dir = str(log.parent.absolute())
            if not container.isdir(log_dir):
                container.make_dir(log_dir, make_parents=True)
