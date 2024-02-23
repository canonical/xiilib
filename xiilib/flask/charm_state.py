# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""This module defines the CharmState class which represents the state of the Flask charm."""

import itertools
import typing

import ops
from charms.data_platform_libs.v0.data_interfaces import DatabaseRequires
from charms.data_platform_libs.v0.s3 import S3Requirer

# pydantic is causing this no-name-in-module problem
from pydantic import (  # pylint: disable=no-name-in-module
    BaseModel,
    Extra,
    Field,
    ValidationError,
    validator,
)

from xiilib._gunicorn.charm_state import GunicornCharmState
from xiilib._gunicorn.secret_storage import GunicornSecretStorage
from xiilib._gunicorn.webserver import WebserverConfig
from xiilib.exceptions import CharmConfigInvalidError


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
    @staticmethod
    def to_upper(value: str) -> str:
        """Convert the string field to uppercase.

        Args:
            value: the input value.

        Returns:
            The string converted to uppercase.
        """
        return value.upper()


# too-many-instance-attributes is okay since we use a factory function to construct the CharmState
class CharmState(GunicornCharmState):  # pylint: disable=too-many-instance-attributes
    """Represents the state of the Flask charm."""

    @classmethod
    def from_charm(
        cls,
        charm: ops.CharmBase,
        secret_storage: GunicornSecretStorage,
        database_requirers: dict[str, DatabaseRequires],
        s3_requirer: S3Requirer | None = None,
    ) -> "CharmState":
        """Initialize a new instance of the CharmState class from the associated charm.

        Args:
            charm: The charm instance associated with this state.
            secret_storage: The secret storage manager associated with the charm.
            database_requirers: All database requirers object declared by the charm.
            s3_requirer: The S3Requirer object associated with the charm.

        Return:
            The CharmState instance created by the provided charm.

        Raises:
            CharmConfigInvalidError: if the charm configuration is invalid.
        """
        flask_config = {
            k.removeprefix("flask-").replace("-", "_"): v
            for k, v in charm.config.items()
            if k.startswith("flask-")
        }
        app_config = {
            k.replace("-", "_"): v
            for k, v in charm.config.items()
            if not any(k.startswith(prefix) for prefix in ("flask-", "webserver-"))
        }
        try:
            valid_flask_config = FlaskConfig(**flask_config)  # type: ignore
        except ValidationError as exc:
            error_fields = set(
                itertools.chain.from_iterable(error["loc"] for error in exc.errors())
            )
            error_field_str = " ".join(f"flask-{f}".replace("_", "-") for f in error_fields)
            raise CharmConfigInvalidError(f"invalid configuration: {error_field_str}") from exc
        flask_config_keys = valid_flask_config.dict().keys()
        app_config = {k: v for k, v in app_config.items() if k not in flask_config_keys}
        return cls(
            framework="flask",
            wsgi_config=valid_flask_config.dict(exclude_unset=True, exclude_none=True),
            app_config=typing.cast(dict[str, str | int | bool], app_config),
            database_requirers=database_requirers,
            webserver_config=WebserverConfig.from_charm(charm),
            secret_key=(
                secret_storage.get_secret_key() if secret_storage.is_initialized else None
            ),
            is_secret_storage_ready=secret_storage.is_initialized,
            s3_requirer=s3_requirer,
        )
