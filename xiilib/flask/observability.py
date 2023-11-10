# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Provide the Observability class to represent the observability stack for Flask application."""
import pathlib
import textwrap

import ops

from xiilib.observability import Observability

from xiilib.flask.constants import FLASK_CONTAINER_NAME
from xiilib.flask.charm_state import CharmState


class FlaskObservability(Observability):
    def __init__(self, charm: ops.CharmBase, charm_state: CharmState):
        super().__init__(
            charm,
            charm_state=charm_state,
            container_name=FLASK_CONTAINER_NAME,
            cos_dir=str((pathlib.Path(__file__).parent / "cos").absolute()),
        )
        self._charm.framework.observe(
            self._charm.on.statsd_prometheus_exporter_pebble_ready,
            self._on_statsd_prometheus_exporter_pebble_ready,
        )

    def _on_statsd_prometheus_exporter_pebble_ready(self, _event: ops.PebbleReadyEvent) -> None:
        """Handle the statsd-prometheus-exporter-pebble-ready event."""
        container = self._charm.unit.get_container("statsd-prometheus-exporter")
        container.push(
            "/statsd.conf",
            textwrap.dedent(
                """\
                mappings:
                  - match: gunicorn.request.status.*
                    name: flask_response_code
                    labels:
                      status: $1
                  - match: gunicorn.requests
                    name: flask_requests
                  - match: gunicorn.request.duration
                    name: flask_request_duration
                """
            ),
        )
        statsd_layer = ops.pebble.LayerDict(
            summary="statsd exporter layer",
            description="statsd exporter layer",
            services={
                "statsd-prometheus-exporter": {
                    "override": "replace",
                    "summary": "statsd exporter service",
                    "user": "nobody",
                    "command": "/bin/statsd_exporter --statsd.mapping-config=/statsd.conf",
                    "startup": "enabled",
                }
            },
            checks={
                "container-ready": {
                    "override": "replace",
                    "level": "ready",
                    "http": {"url": "http://localhost:9102/metrics"},
                },
            },
        )
        container.add_layer("statsd-prometheus-exporter", statsd_layer, combine=True)
        container.replan()
