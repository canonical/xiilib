# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Provide the SecretStorage for managing the persistent secret storage for the Flask charm."""
import secrets

import ops

from xiilib.secret_storage import SecretStorage


class FlaskSecretStorage(SecretStorage):
    """A class that manages secret keys required by the FlaskCharm."""

    def gen_initial_value(self) -> dict[str, str]:
        """Generate the initial secret values.

        Returns:
            The initial secret values.
        """
        return {"flask_secret_key": secrets.token_urlsafe(32)}

    def __init__(self, charm: ops.CharmBase):
        """Initialize the SecretStorage with a given FlaskCharm object.

        Args:
            charm (FlaskCharm): The FlaskCharm object that uses the SecretStorage.
        """
        super().__init__(charm=charm, keys=["flask_secret_key"])
        self._charm = charm

    def get_flask_secret_key(self) -> str:
        """Retrieve the Flask secret key from the peer relation data.

        Returns:
            The Flask secret key.
        """
        return self.get_secret("flask_secret_key")

    def reset_flask_secret_key(self) -> None:
        """Generate a new Flask secret key and store it within the peer relation data."""
        self.set_secret("flask_secret_key", secrets.token_urlsafe(32))
