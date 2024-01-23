# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Provide the SecretStorage for managing the persistent secret storage for charms."""
import abc
import typing

import ops


class SecretStorageReady(ops.EventBase):
    def __init__(self, handle, initial_value: dict[str, str]):
        super().__init__(handle)
        self.initial_value = initial_value


class DatabasesEvents(ops.ObjectEvents):
    all_databases_ready = ops.EventSource(SecretStorageReady)


class SecretStorage(ops.Object, abc.ABC):
    """A class that manages secret keys required for charms.

    Attrs:
        is_initialized: True if the SecretStorage has been initialized.
    """

    def __init__(
        self,
        charm: ops.CharmBase,
        initial_values: dict[str, str],
        peer_relation_name: str = "secret-storage",
    ):
        """Initialize the SecretStorage with a given Charm object.

        Args:
            charm: The charm object that uses the SecretStorage.
            peer_relation_name: the name of the peer relation to be used to store secrets.
        """
        super().__init__(parent=charm, key=peer_relation_name)
        self._charm = charm
        self._initial_values = initial_values
        self._keys = list(self._initial_values.keys())
        self._peer_relation_name = peer_relation_name
        charm.framework.observe(
            self._charm.on[self._peer_relation_name].relation_created,
            self._set_initial_values,
        )
        charm.framework.observe(
            self._charm.on[self._peer_relation_name].relation_changed,
            self._set_initial_values,
        )

    def _set_initial_values(self, event: ops.RelationEvent) -> None:
        """Handle the event when a new peer relation is created.

        Generates a new secret key and stores it within the relation's data.

        Args:
            event: The event that triggered this handler.
        """
        if not self._charm.unit.is_leader():
            return
        relation_data = event.relation.data[self._charm.app]
        for key, value in self._initial_values.items():
            if not relation_data.get(key):
                relation_data[key] = value

    @property
    def is_initialized(self) -> bool:
        """Check if the SecretStorage has been initialized.

        It's an error to read or write the secret storage before initialization.

        Returns:
            True if SecretStorage is initialized, False otherwise.
        """
        relation = self._charm.model.get_relation(self._peer_relation_name)
        if relation is None:
            return False
        relation_data = relation.data[self._charm.app]
        return all(relation_data.get(k) for k in self._keys)

    def set_secret(self, key: str, value: str) -> None:
        """Set the secret value in the relation data.

        Args:
            key: the secret value key.
            value: the secret value.

        Raises:
            RuntimeError: If SecretStorage is not initialized.
        """
        if not self.is_initialized:
            raise RuntimeError("SecretStorage is not initialized")
        relation = typing.cast(
            ops.Relation, self._charm.model.get_relation(self._peer_relation_name)
        )
        relation.data[self._charm.app][key] = value

    def get_secret(self, key: str) -> str:
        """Retrieve the secret value from the relation data.

        Args:
            key: the secret value key.

        Returns:
            The value of the associated key in the relation data.

        Raises:
            RuntimeError: If SecretStorage is not initialized.
        """
        if not self.is_initialized:
            raise RuntimeError("SecretStorage is not initialized")
        relation = typing.cast(
            ops.Relation, self._charm.model.get_relation(self._peer_relation_name)
        )
        return relation.data[self._charm.app][key]
