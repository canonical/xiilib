#!/usr/bin/env python3

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Flask Charm service."""
import itertools
import logging
import pathlib

import ops

# pydantic is causing this no-name-in-module problem
from pydantic import (  # pylint: disable=no-name-in-module
    BaseModel,
    Extra,
    Field,
    ValidationError,
    field_validator,
)

from xiilib._gunicorn.charm import GunicornBase
from xiilib.exceptions import CharmConfigInvalidError

logger = logging.getLogger(__name__)


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

    env: str | None = Field(default=None, min_length=1)
    debug: bool | None = Field(default=None)
    secret_key: str | None = Field(default=None, min_length=1)
    permanent_session_lifetime: int | None = Field(default=None, gt=0)
    application_root: str | None = Field(default=None, min_length=1)
    session_cookie_secure: bool | None = Field(default=None)
    preferred_url_scheme: str | None = Field(default=None, pattern="(?i)^(HTTP|HTTPS)$")

    @field_validator("preferred_url_scheme")
    @staticmethod
    def to_upper(value: str) -> str:
        """Convert the string field to uppercase.

        Args:
            value: the input value.

        Returns:
            The string converted to uppercase.
        """
        return value.upper()


class Charm(GunicornBase):  # pylint: disable=too-many-instance-attributes
    """Flask Charm service."""

    def __init__(self, framework: ops.Framework) -> None:
        """Initialize the Flask charm.

        Args:
            framework: operator framework.
        """
        super().__init__(framework=framework, wsgi_framework="flask")
        self.framework.observe(self.on.flask_app_pebble_ready, self._on_flask_app_pebble_ready)

    def get_wsgi_config(self) -> BaseModel:
        """Return Flask framework related configurations.

        Returns:
             Flask framework related configurations.

        Raises:
            CharmConfigInvalidError: if charm config is not valid.
        """
        flask_config = {
            k.removeprefix("flask-").replace("-", "_"): v
            for k, v in self.config.items()
            if k.startswith("flask-")
        }
        try:
            return FlaskConfig.model_validate(flask_config)
        except ValidationError as exc:
            error_fields = set(
                itertools.chain.from_iterable(error["loc"] for error in exc.errors())
            )
            error_field_str = " ".join(f"flask-{f}".replace("_", "-") for f in error_fields)
            raise CharmConfigInvalidError(f"invalid configuration: {error_field_str}") from exc

    def get_cos_dir(self) -> str:
        """Return the directory with COS related files.

        Returns:
            Return the directory with COS related files.
        """
        return str((pathlib.Path(__file__).parent / "cos").absolute())

    def _on_flask_app_pebble_ready(self, _: ops.PebbleReadyEvent) -> None:
        """Handle the pebble-ready event."""
        self.restart()
