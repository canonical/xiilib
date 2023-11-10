# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""This module defines the CharmState class which represents the state of the Flask charm."""

import datetime
import itertools
import os
import pathlib
import typing

# pydantic is causing this no-name-in-module problem
from pydantic import (  # pylint: disable=no-name-in-module
    AnyHttpUrl,
    BaseModel,
    Extra,
    Field,
    ValidationError,
    parse_obj_as,
    validator,
)

from xiilib.flask.constants import FLASK_APP_DIR
from xiilib.exceptions import CharmConfigInvalidError
from xiilib.flask.secret_storage import FlaskSecretStorage
from xiilib.webserver import WebserverConfig

if typing.TYPE_CHECKING:
    from charm import FlaskCharm

KNOWN_CHARM_CONFIG = (
    "database_migration_script",
    "flask_application_root",
    "flask_debug",
    "flask_env",
    "flask_permanent_session_lifetime",
    "flask_preferred_url_scheme",
    "flask_secret_key",
    "flask_session_cookie_secure",
    "webserver_keepalive",
    "webserver_threads",
    "webserver_timeout",
    "webserver_workers",
    "webserver_wsgi_path",
)


class FlaskConfig(BaseModel, extra=Extra.allow):  # pylint: disable=too-few-public-methods
    """Represent Flask builtin configuration values.

    Attrs:
        env: what environment the Flask app is running in, by default it's 'production'.
        debug: whether Flask debug mode is enabled.
        secret_key: a secret key that will be used for securely signing the session cookie
            and can be used for any other security related needs by your Flask application.
        permanent_session_lifetime: set the cookie’s expiration to this number of seconds in the
            Flask application permanent sessions.
        application_root: inform the Flask application what path it is mounted under by the
            application / web server.
        session_cookie_secure: set the secure attribute in the Flask application cookies.
        preferred_url_scheme: use this scheme for generating external URLs when not in a request
            context in the Flask application.
    """

    env: str | None = Field(None, min_length=1)
    debug: bool | None = Field(None)
    secret_key: str | None = Field(None, min_length=1)
    permanent_session_lifetime: int | None = Field(None, gt=0)
    application_root: str | None = Field(None, min_length=1)
    session_cookie_secure: bool | None = Field(None)
    preferred_url_scheme: str | None = Field(None, regex="(?i)^(HTTP|HTTPS)$")

    @validator("preferred_url_scheme")
    @classmethod
    def to_upper(cls, value: str) -> str:
        """Convert the string field to uppercase.

        Args:
            value: the input value.

        Returns:
            The string converted to uppercase.
        """
        return value.upper()


class ProxyConfig(BaseModel):  # pylint: disable=too-few-public-methods
    """Configuration for accessing Jenkins through proxy.

    Attributes:
        http_proxy: The http proxy URL.
        https_proxy: The https proxy URL.
        no_proxy: Comma separated list of hostnames to bypass proxy.
    """

    http_proxy: typing.Optional[AnyHttpUrl]
    https_proxy: typing.Optional[AnyHttpUrl]
    no_proxy: typing.Optional[str]


# too-many-instance-attributes is okay since we use a factory function to construct the CharmState
class CharmState:  # pylint: disable=too-many-instance-attributes
    """Represents the state of the Flask charm.

    Attrs:
        webserver_config: the web server configuration file content for the charm.
        flask_config: the value of the flask_config charm configuration.
        app_config: user-defined configurations for the Flask application.
        database_migration_script: The database migration script path.
        database_uris: a mapping of available database environment variable to database uris.
        port: the port number to use for the Flask server.
        application_log_file: the file path for the Flask access log.
        application_error_log_file: the file path for the Flask error log.
        statsd_host: the statsd server host for Flask metrics.
        flask_secret_key: the charm managed flask secret key.
        is_secret_storage_ready: whether the secret storage system is ready.
        proxy: proxy information.
    """

    def __init__(  # pylint: disable=too-many-arguments
        self,
        *,
        app_config: dict[str, int | str | bool] | None = None,
        database_migration_script: str | None = None,
        database_uris: dict[str, str] | None = None,
        flask_config: dict[str, int | str] | None = None,
        flask_secret_key: str | None = None,
        is_secret_storage_ready: bool,
        webserver_workers: int | None = None,
        webserver_threads: int | None = None,
        webserver_keepalive: int | None = None,
        webserver_timeout: int | None = None,
    ):
        """Initialize a new instance of the CharmState class.

        Args:
            app_config: User-defined configuration values for the Flask configuration.
            flask_config: The value of the flask_config charm configuration.
            flask_secret_key: The secret storage manager associated with the charm.
            database_migration_script: The database migration script path
            database_uris: The database uri environment variables.
            is_secret_storage_ready: whether the secret storage system is ready.
            webserver_workers: The number of workers to use for the web server,
                or None if not specified.
            webserver_threads: The number of threads per worker to use for the web server,
                or None if not specified.
            webserver_keepalive: The time to wait for requests on a Keep-Alive connection,
                or None if not specified.
            webserver_timeout: The request silence timeout for the web server,
                or None if not specified.
        """
        self._webserver_workers = webserver_workers
        self._webserver_threads = webserver_threads
        self._webserver_keepalive = webserver_keepalive
        self._webserver_timeout = webserver_timeout
        self._flask_config = flask_config if flask_config is not None else {}
        self._app_config = app_config if app_config is not None else {}
        self._is_secret_storage_ready = is_secret_storage_ready
        self._flask_secret_key = flask_secret_key
        self.database_uris = database_uris if database_uris is not None else {}
        self.database_migration_script = database_migration_script

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

    @classmethod
    def from_charm(
        cls, charm: "FlaskCharm", secret_storage: FlaskSecretStorage, database_uris: dict[str, str]
    ) -> "CharmState":
        """Initialize a new instance of the CharmState class from the associated charm.

        Args:
            charm: The charm instance associated with this state.
            secret_storage: The secret storage manager associated with the charm.
            database_uris: The database uri environment variables.

        Return:
            The CharmState instance created by the provided charm.

        Raises:
            CharmConfigInvalidError: if the charm configuration is invalid.
        """
        keepalive = charm.config.get("webserver_keepalive")
        timeout = charm.config.get("webserver_timeout")
        workers = charm.config.get("webserver_workers")
        threads = charm.config.get("webserver_threads")
        flask_config = {
            k.removeprefix("flask_"): v
            for k, v in charm.config.items()
            if k.startswith("flask_") and k in KNOWN_CHARM_CONFIG
        }
        app_config = {k: v for k, v in charm.config.items() if k not in KNOWN_CHARM_CONFIG}
        try:
            valid_flask_config = FlaskConfig(**flask_config)  # type: ignore
        except ValidationError as exc:
            error_fields = set(
                itertools.chain.from_iterable(error["loc"] for error in exc.errors())
            )
            error_field_str = " ".join(f"flask_{f}" for f in error_fields)
            raise CharmConfigInvalidError(f"invalid configuration: {error_field_str}") from exc
        database_migration_script = charm.config.get("database_migration_script")
        if database_migration_script:
            database_migration_script = os.path.normpath(FLASK_APP_DIR / database_migration_script)
            if not database_migration_script.startswith(str(FLASK_APP_DIR)):
                raise CharmConfigInvalidError(
                    f"database_migration_script is not inside {FLASK_APP_DIR}"
                )
        return cls(
            flask_config=valid_flask_config.dict(exclude_unset=True, exclude_none=True),
            app_config=typing.cast(dict[str, str | int | bool], app_config),
            database_migration_script=database_migration_script,
            database_uris=database_uris,
            webserver_workers=int(workers) if workers is not None else None,
            webserver_threads=int(threads) if threads is not None else None,
            webserver_keepalive=int(keepalive) if keepalive is not None else None,
            webserver_timeout=int(timeout) if timeout is not None else None,
            flask_secret_key=secret_storage.get_flask_secret_key()
            if secret_storage.is_initialized
            else None,
            is_secret_storage_ready=secret_storage.is_initialized,
        )

    @property
    def webserver_config(self) -> WebserverConfig:
        """Get the web server configuration file content for the charm.

        Returns:
            The web server configuration file content for the charm.
        """
        return WebserverConfig(
            workers=self._webserver_workers,
            threads=self._webserver_threads,
            keepalive=datetime.timedelta(seconds=int(self._webserver_keepalive))
            if self._webserver_keepalive is not None
            else None,
            timeout=datetime.timedelta(seconds=int(self._webserver_timeout))
            if self._webserver_timeout is not None
            else None,
        )

    @property
    def flask_config(self) -> dict[str, str | int | bool]:
        """Get the value of the flask_config charm configuration.

        Returns:
            The value of the flask_config charm configuration.
        """
        return self._flask_config.copy()

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
    def application_log_file(self) -> pathlib.Path:
        """Returns the file path for the Flask access log.

        Returns:
            The file path for the Flask access log.
        """
        return pathlib.Path("/var/log/flask/access.log")

    @property
    def application_error_log_file(self) -> pathlib.Path:
        """Returns the file path for the Flask error log.

        Returns:
            The file path for the Flask error log.
        """
        return pathlib.Path("/var/log/flask/error.log")

    @property
    def statsd_host(self) -> str:
        """Returns the statsd server host for Flask metrics.

        Returns:
            The statsd server host for Flask metrics.
        """
        return "localhost:9125"

    @property
    def flask_secret_key(self) -> str:
        """Return the flask secret key stored in the SecretStorage.

        It's an error to read the secret key before SecretStorage is initialized.

        Returns:
            The flask secret key stored in the SecretStorage.

        Raises:
            RuntimeError: raised when accessing flask secret key before secret storage is ready
        """
        if self._flask_secret_key is None:
            raise RuntimeError("access flask secret key before secret storage is ready")
        return self._flask_secret_key

    @property
    def is_secret_storage_ready(self) -> bool:
        """Return whether the secret storage system is ready.

        Returns:
            Whether the secret storage system is ready.
        """
        return self._is_secret_storage_ready
