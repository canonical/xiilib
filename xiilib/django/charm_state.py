# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""This module defines the CharmState class which represents the state of the Flask charm."""

import itertools
import typing

import ops
from charms.data_platform_libs.v0.data_interfaces import DatabaseRequires
from charms.data_platform_libs.v0.s3 import S3Requirer

# pydantic is causing this no-name-in-module problem
from pydantic import BaseModel, Extra, Field, ValidationError  # pylint: disable=no-name-in-module

from xiilib._gunicorn.charm_state import GunicornCharmState
from xiilib._gunicorn.secret_storage import GunicornSecretStorage
from xiilib._gunicorn.webserver import WebserverConfig
from xiilib.exceptions import CharmConfigInvalidError


class DjangoConfig(BaseModel, extra=Extra.allow):  # pylint: disable=too-few-public-methods
    """Represent Django builtin configuration values.

    Attrs:
        debug: whether Django debug mode is enabled.
        secret_key: a secret key that will be used for security related needs by your
            Django application.
        allowed_hosts: a list of host/domain names that this Django site can serve.
    """

    debug: bool | None = Field(None)
    secret_key: str | None = Field(None, min_length=1)
    allowed_hosts: list[str]


# too-many-instance-attributes is okay since we use a factory function to construct the CharmState
class CharmState(GunicornCharmState):  # pylint: disable=too-many-instance-attributes
    """Represents the state of the Django charm."""

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
        django_config: dict[str, typing.Any] = {
            "debug": charm.config.get("django-debug"),
            "secret_key": charm.config.get("django-secret-key"),
        }
        allowed_hosts = charm.config.get("django-allowed-hosts", "")
        if allowed_hosts.strip():
            django_config["allowed_hosts"] = [h.strip() for h in allowed_hosts.split(",")]
        else:
            django_config["allowed_hosts"] = []
        app_config = {
            k.replace("-", "_"): v
            for k, v in charm.config.items()
            if not any(k.startswith(prefix) for prefix in ("django-", "webserver-"))
        }
        try:
            valid_django_config = DjangoConfig(**django_config)  # type: ignore
        except ValidationError as exc:
            error_fields = set(
                itertools.chain.from_iterable(error["loc"] for error in exc.errors())
            )
            error_field_str = " ".join(f"django-{f}".replace("_", "-") for f in error_fields)
            raise CharmConfigInvalidError(f"invalid configuration: {error_field_str}") from exc
        django_config_keys = valid_django_config.dict().keys()
        app_config = {k: v for k, v in app_config.items() if k not in django_config_keys}
        return cls(
            framework="django",
            wsgi_config=valid_django_config.dict(exclude_unset=True, exclude_none=True),
            app_config=typing.cast(dict[str, str | int | bool], app_config),
            database_requirers=database_requirers,
            webserver_config=WebserverConfig.from_charm(charm),
            secret_key=(
                secret_storage.get_secret_key() if secret_storage.is_initialized else None
            ),
            is_secret_storage_ready=secret_storage.is_initialized,
            s3_requirer=s3_requirer,
        )
