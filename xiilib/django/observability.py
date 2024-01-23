import pathlib
import typing

import ops

from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.loki_k8s.v0.loki_push_api import LogProxyConsumer
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider


class Observability(ops.Object):  # pylint: disable=too-few-public-methods
    """A class representing the observability stack for charm managed application."""

    def __init__(
        self,
        charm: ops.CharmBase,
        container: str,
        cos_dir: pathlib.Path,
        log_files: typing.Sequence[str],
        metrics_port: int,
    ):
        """Initialize a new instance of the Observability class.

        Args:
            charm: The charm object that the Observability instance belongs to.
            container: The name of the application container.
            cos_dir: The directories containing the grafana_dashboards, loki_alert_rules and
                prometheus_alert_rules.
        """
        super().__init__(charm, "observability")
        self._charm = charm
        self._metrics_endpoint = MetricsEndpointProvider(
            charm,
            alert_rules_path=str(cos_dir / "prometheus_alert_rules"),
            jobs=[{"static_configs": [{"targets": [f"*:{metrics_port}"]}]}],
            relation_name="metrics-endpoint",
        )
        if log_files:
            self._logging = LogProxyConsumer(
                charm,
                alert_rules_path=str(cos_dir / "loki_alert_rules"),
                container_name=container,
                log_files=list(log_files),
                relation_name="logging",
            )
        self._grafana_dashboards = GrafanaDashboardProvider(
            charm,
            dashboards_path=str(cos_dir / "grafana_dashboards"),
            relation_name="grafana-dashboard",
        )
