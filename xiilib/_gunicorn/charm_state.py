# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""This module defines the CharmState class which represents the state of the Flask charm."""
import abc
import os
import pathlib
import typing

from charms.data_platform_libs.v0.data_interfaces import DatabaseRequires
from charms.data_platform_libs.v0.s3 import S3Requirer

# pydantic is causing this no-name-in-module problem
from pydantic import AnyHttpUrl, BaseModel, parse_obj_as  # pylint: disable=no-name-in-module

from xiilib._gunicorn.webserver import WebserverConfig
from xiilib.databases import get_uris


class ProxyConfig(BaseModel):  # pylint: disable=too-few-public-methods
    """Configuration for network access through proxy.

    Attributes:
        http_proxy: The http proxy URL.
        https_proxy: The https proxy URL.
        no_proxy: Comma separated list of hostnames to bypass proxy.
    """

    http_proxy: typing.Optional[AnyHttpUrl]
    https_proxy: typing.Optional[AnyHttpUrl]
    no_proxy: typing.Optional[str]


# too-many-instance-attributes is okay since we use a factory function to construct the CharmState
class GunicornCharmState(abc.ABC):  # pylint: disable=too-many-instance-attributes
    """Represents the state of the Flask charm.

    Attrs:
        webserver_config: the web server configuration file content for the charm.
        wsgi_config: the value of the flask_config charm configuration.
        app_config: user-defined configurations for the Flask application.
        database_uris: a mapping of available database environment variable to database uris.
        port: the port number to use for the Flask server.
        application_log_file: the file path for the Flask access log.
        application_error_log_file: the file path for the Flask error log.
        statsd_host: the statsd server host for Flask metrics.
        secret_key: the charm managed flask secret key.
        is_secret_storage_ready: whether the secret storage system is ready.
        proxy: proxy information.
        service_name: The WSGI application pebble service name.
        container_name: The name of the WSGI application container.
        base_dir: The project base directory in the WSGI application container.
        app_dir: The WSGI application directory in the WSGI application container.
        s3: the S3 compatible API credentials.
    """

    def __init__(  # pylint: disable=too-many-arguments
        self,
        *,
        framework: str,
        webserver_config: WebserverConfig,
        is_secret_storage_ready: bool,
        app_config: dict[str, int | str | bool] | None = None,
        database_requirers: dict[str, DatabaseRequires] | None = None,
        s3_requirer: S3Requirer | None = None,
        wsgi_config: dict[str, int | str] | None = None,
        secret_key: str | None = None,
    ):
        """Initialize a new instance of the CharmState class.

        Args:
            framework: the framework name.
            webserver_config: the Gunicorn webserver configuration.
            is_secret_storage_ready: whether the secret storage system is ready.
            app_config: User-defined configuration values for the Flask configuration.
            wsgi_config: The value of the flask_config charm configuration.
            secret_key: The secret storage manager associated with the charm.
            database_requirers: All declared database requirers.
            s3_requirer: The S3Requirer object.
        """
        self.framework = framework
        self.service_name = self.framework
        self.container_name = f"{self.framework}-app"
        self.base_dir = pathlib.Path(f"/{framework}")
        self.app_dir = self.base_dir / "app"
        self.state_dir = self.base_dir / "state"
        self.application_log_file = pathlib.Path(f"/var/log/{self.framework}/access.log")
        self.application_error_log_file = pathlib.Path(f"/var/log/{self.framework}/error.log")
        self.webserver_config = webserver_config
        self._wsgi_config = wsgi_config if wsgi_config is not None else {}
        self._app_config = app_config if app_config is not None else {}
        self._is_secret_storage_ready = is_secret_storage_ready
        self._secret_key = secret_key
        self._database_requirers = database_requirers if database_requirers else {}
        self._s3_requirer = s3_requirer if s3_requirer is not None else None

    @property
    def proxy(self) -> "ProxyConfig":
        """Get charm proxy information from juju charm environment.

        Returns:
            charm proxy information in the form of `ProxyConfig`.
        """
        http_proxy = os.environ.get("JUJU_CHARM_HTTP_PROXY")
        https_proxy = os.environ.get("JUJU_CHARM_HTTPS_PROXY")
        no_proxy = os.environ.get("JUJU_CHARM_NO_PROXY")
        return ProxyConfig(
            http_proxy=parse_obj_as(AnyHttpUrl, http_proxy) if http_proxy else None,
            https_proxy=parse_obj_as(AnyHttpUrl, https_proxy) if https_proxy else None,
            no_proxy=no_proxy,
        )

    @property
    def wsgi_config(self) -> dict[str, str | int | bool]:
        """Get the value of the flask_config charm configuration.

        Returns:
            The value of the flask_config charm configuration.
        """
        return self._wsgi_config.copy()

    @property
    def app_config(self) -> dict[str, str | int | bool]:
        """Get the value of user-defined Flask application configurations.

        Returns:
            The value of user-defined Flask application configurations.
        """
        return self._app_config.copy()

    @property
    def port(self) -> int:
        """Gets the port number to use for the Flask server.

        Returns:
            The port number to use for the Flask server.
        """
        return 8000

    @property
    def statsd_host(self) -> str:
        """Returns the statsd server host for Flask metrics.

        Returns:
            The statsd server host for Flask metrics.
        """
        return "localhost:9125"

    @property
    def secret_key(self) -> str:
        """Return the flask secret key stored in the SecretStorage.

        It's an error to read the secret key before SecretStorage is initialized.

        Returns:
            The flask secret key stored in the SecretStorage.

        Raises:
            RuntimeError: raised when accessing flask secret key before secret storage is ready
        """
        if self._secret_key is None:
            raise RuntimeError("access secret key before secret storage is ready")
        return self._secret_key

    @property
    def is_secret_storage_ready(self) -> bool:
        """Return whether the secret storage system is ready.

        Returns:
            Whether the secret storage system is ready.
        """
        return self._is_secret_storage_ready

    @property
    def database_uris(self) -> dict[str, str]:
        """Return currently attached database URIs.

        Returns:
            A dictionary of database types and database URIs.
        """
        return get_uris(self._database_requirers)

    @property
    def s3(self) -> dict[str, str]:
        """Return the s3 connection info.

        Returns:
            A dictionary contains the s3 compatible API connection info.
        """
        if self._s3_requirer is None:
            return {}
        return {k: v for k, v in self._s3_requirer.get_s3_connection_info().items() if k != "data"}
