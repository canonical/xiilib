import logging
import pathlib
import typing

import ops
import yaml
from charms.data_platform_libs.v0.data_interfaces import DatabaseRequires

logger = logging.getLogger(__name__)


class AllDatabasesReady(ops.EventBase):
    def __init__(self, handle, databases: "Databases"):
        super().__init__(handle)
        self.databases = databases
        self.uris = databases.get_uris()


class DatabasesEvents(ops.ObjectEvents):
    all_databases_ready = ops.EventSource(AllDatabasesReady)


class Databases(ops.Object):
    SUPPORTED_DB_INTERFACES = {"mysql_client": "mysql", "postgresql_client": "postgresql"}

    on = DatabasesEvents()

    def __init__(self, charm: ops.CharmBase, database_name: str) -> None:
        super().__init__(charm, "databases")
        self._charm = charm
        self._database_name = database_name
        self._requirers = self._make_database_requirers()
        for requirer in self._requirers.values():
            self.framework.observe(requirer.on.database_created, self._on_database_event)
            self.framework.observe(requirer.on.endpoints_changed, self._on_database_event)

    def _make_database_requirers(self) -> typing.Dict[str, DatabaseRequires]:
        """Create database requirer objects for the charm.

        Returns: A dictionary which is the database uri environment variable name and the
            value is the corresponding database requirer object.
        """
        metadata_file = pathlib.Path("metadata.yaml")
        if not metadata_file.exists():
            metadata_file = pathlib.Path("charmcraft.yaml")
        metadata = yaml.safe_load(metadata_file.read_text(encoding="utf-8"))
        db_interfaces = (
            self.SUPPORTED_DB_INTERFACES[require["interface"]]
            for require in metadata["requires"].values()
            if require["interface"] in self.SUPPORTED_DB_INTERFACES
        )
        # automatically create database relation requirers to manage database relations
        # one database relation requirer is required for each of the database relations
        # create a dictionary to hold the requirers
        databases = {
            name: DatabaseRequires(
                self._charm,
                relation_name=name,
                database_name=self._database_name,
            )
            for name in db_interfaces
        }
        return databases

    def get_uris(self) -> typing.Dict[str, str]:
        """Compute DatabaseURI and return it.

        Returns:
            DatabaseURI containing details about the data provider integration
        """
        db_uris: typing.Dict[str, str] = {}

        for interface_name, requirer in self._requirers.items():
            relation_data = list(
                requirer.fetch_relation_data(
                    fields=["endpoints", "username", "password", "database"]
                ).values()
            )

            if not relation_data:
                continue

            # There can be only one database integrated at a time
            # with the same interface name. See: metadata.yaml
            data = relation_data[0]

            # Check that the relation data is well-formed according to the following json_schema:
            # https://github.com/canonical/charm-relation-interfaces/blob/main/interfaces/mysql_client/v0/schemas/provider.json
            if not all(data.get(key) for key in ("endpoints", "username", "password")):
                logger.warning("Incorrect relation data from the data provider: %s", data)
                continue

            database_name = data.get("database", requirer.database)
            endpoint = data["endpoints"].split(",")[0]
            db_uris[f"{interface_name.upper()}_DB_CONNECT_STRING"] = (
                f"{interface_name}://"
                f"{data['username']}:{data['password']}"
                f"@{endpoint}/{database_name}"
            )
        return db_uris

    def is_ready(self):
        return len(self.get_uris()) == len(self._requirers)

    def _on_database_event(self, _event: ops.EventBase):
        if self.is_ready():
            self.on.all_databases_ready.emit(databases=self)
