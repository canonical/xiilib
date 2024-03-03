#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""WSGI server classes."""
import logging
import pathlib
import shlex
import signal
import textwrap

import ops
import yaml

logger = logging.getLogger(__name__)


class WebserverError(Exception):
    """Base class for exceptions in webservers."""


class GunicornServer:
    """Gunicorn server controller."""

    def __init__(
        self,
        charm: ops.CharmBase,
        container: str,
        base_dir: pathlib.Path,
        service_name: str,
        statsd_host: str = "localhost:9125",
    ):
        self._charm = charm
        self._container = charm.unit.get_container(container)
        self._base_dir = base_dir.absolute()
        self._service_name = service_name
        self._statsd_host = statsd_host
        self.access_log = "/var/log/gunicorn/access.log"
        self.error_log = "/var/log/gunicorn/access.log"
        self.port = 8000

    @property
    def _working_dir(self) -> str:
        return str(self._base_dir / "app")

    def _gen_config_file(self) -> str:
        keepalive = self._charm.config.get("webserver_keepalive")
        timeout = self._charm.config.get("webserver_timeout")
        workers = self._charm.config.get("webserver_workers")
        threads = self._charm.config.get("webserver_threads")
        config = textwrap.dedent(
            f"""\
            bind = ['0.0.0.0:{self.port}']
            chdir = {repr(self._working_dir)}
            accesslog = {repr(str(self.access_log))}
            errorlog = {repr(str(self.error_log))}
            statsd_host = {repr(self._statsd_host)}"""
        )
        if keepalive is not None:
            config += f"\nkeepalive = {repr(keepalive)}"
        if timeout is not None:
            config += f"\ntimeout = {repr(timeout)}"
        if workers is not None:
            config += f"\nworkers = {repr(workers)}"
        if threads is not None:
            config += f"\nthreads = {repr(threads)}"
        return config

    @property
    def _config_file(self) -> str:
        return str(self._base_dir / "gunicorn.conf.py")

    def _refresh_config_file(self) -> bool:
        file = self._container.pull(self._config_file)
        config = self._gen_config_file()
        if config == file:
            return False
        self._container.push(self._config_file, config)
        return True

    def apply(self, env: dict[str, str]) -> None:
        config_updated = self._refresh_config_file()
        self._container.make_dir("/var/log/gunicorn/", make_parents=True, user="_daemon_")

        check_command = shlex.split(
            self._container.get_plan().services[self._service_name].command
        )
        check_command.append("--check-config")
        exec_process = self._container.exec(
            check_command, environment=env, user="_daemon_", working_dir=self._working_dir
        )
        try:
            exec_process.wait_output()
        except ops.pebble.ExecError as exc:
            logger.error(
                "webserver configuration check failed, stdout: %s, stderr: %s",
                exc.stdout,
                exc.stderr,
            )
            raise WebserverError("gunicorn configuration check failed")

        layer_files = self._container.list_files("/var/lib/pebble/default/layers/")
        original_layer = yaml.safe_load(self._container.pull(layer_files[0].path).read())
        original_services = original_layer["services"]
        for service in original_services.values():
            service["override"] = "replace"
        original_env = original_services[self._service_name].get("environment", {})
        original_services[self._service_name]["environment"] = {**original_env, **env}
        self._container.add_layer("test-django", original_layer, combine=True)

        if config_updated and self.is_running():
            self._container.send_signal(signal.SIGHUP, self._service_name)

        self._container.replan()

    def is_running(self):
        return self._container.get_service(self._service_name).is_running()
