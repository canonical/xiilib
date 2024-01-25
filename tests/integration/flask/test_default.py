# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for flask-k8s charm default image."""

import typing

import requests
from juju.model import Model


async def test_default_image(
    model: Model,
    flask_app_image: str,
    charm_file: str,
    get_unit_ips: typing.Callable[[str], typing.Awaitable[tuple[str, ...]]],
):
    """
    arrange: none.
    act: build and deploy the flask-k8s charm with default image as the flask-app-image.
    assert: flask-k8s charm should run the default Flask application.
    """
    resources = {
        "flask-app-image": flask_app_image,
        "statsd-prometheus-exporter-image": "prom/statsd-exporter",
    }
    app_name = "flask-sentinel"
    await model.deploy(charm_file, resources=resources, application_name=app_name, series="jammy")
    await model.wait_for_idle(apps=[app_name], raise_on_blocked=True)
    for unit_ip in await get_unit_ips(app_name):
        resp = requests.get(f"http://{unit_ip}:8000", timeout=10)
        assert resp.ok
        assert "Welcome to flask-k8s Charm" in resp.text
