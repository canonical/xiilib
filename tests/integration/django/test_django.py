#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for Flask charm."""
import typing

import pytest
import requests
from juju.model import Model


@pytest.mark.parametrize(
    "update_config, timeout",
    [
        pytest.param({"webserver-timeout": 7}, 7, id="timeout=7"),
        pytest.param({"webserver-timeout": 5}, 5, id="timeout=5"),
        pytest.param({"webserver-timeout": 3}, 3, id="timeout=3"),
    ],
    indirect=["update_config"],
)
@pytest.mark.usefixtures("update_config")
async def test_django_webserver_timeout(django_app, get_unit_ips, timeout):
    """
    arrange: build and deploy the django charm, and change the gunicorn timeout configuration.
    act: send long-running requests to the django application managed by the flask charm.
    assert: the gunicorn should restart the worker if the request duration exceeds the timeout.
    """
    safety_timeout = timeout + 3
    for unit_ip in await get_unit_ips(django_app.name):
        assert requests.get(
            f"http://{unit_ip}:8000/sleep?duration={timeout - 1}", timeout=safety_timeout
        ).ok
        with pytest.raises(requests.ConnectionError):
            requests.get(
                f"http://{unit_ip}:8000/sleep?duration={timeout + 1}", timeout=safety_timeout
            )


async def test_flask_database_migration(django_app, get_unit_ips):
    """
    arrange: build and deploy the django charm with database migration enabled.
    act: access an endpoint requiring database.
    assert: request succeed.
    """
    for unit_ip in await get_unit_ips(django_app.name):
        assert requests.get(f"http://{unit_ip}:8000/len/users", timeout=1).ok


@pytest.mark.parametrize(
    "update_config, expected_settings",
    [
        pytest.param(
            {"django-allowed-hosts": "*,test"}, {"ALLOWED_HOSTS": ["*", "test"]}, id="allowed-host"
        ),
        pytest.param({"django-secret-key": "test"}, {"SECRET_KEY": "test"}, id="secret-key"),
    ],
    indirect=["update_config"],
)
@pytest.mark.usefixtures("update_config")
async def test_django_charm_config(django_app, expected_settings, get_unit_ips):
    """
    arrange: build and deploy the django charm, and change the django related configuration.
    act: send request to the django application to retrieve the corresponding settings.
    assert: settings in django application correctly updated according to the charm configuration.
    """
    for unit_ip in await get_unit_ips(django_app.name):
        for setting, value in expected_settings.items():
            url = f"http://{unit_ip}:8000/settings/{setting}"
            assert value == requests.get(url, timeout=5).json()


async def test_s3_integrator(django_app, get_unit_ips, model: Model):
    """
    arrange: deploy and set up the s3-integrator charm.
    act: retrieve environment variables from the django application.
    assert: environment variables match the setting in s3-integrator.
    """

    s3_integrator = await model.deploy("s3-integrator")
    await model.wait_for_idle()
    action = (
        await model.applications["s3-integrator"]
        .units[0]
        .run_action("sync-s3-credentials", **{"access-key": "test", "secret-key": "test"})
    )
    await action.wait()

    await s3_integrator.set_config(
        {
            "endpoint": "https://example.com",
            "bucket": "test",
            "region": "us-east-1",
            "storage-class": "foobar",
            "attributes": "test,example",
        }
    )
    await model.relate("s3-integrator", "django-k8s")
    await model.wait_for_idle(status="active")
    expected_env = {
        "S3_ENDPOINT": "https://example.com",
        "S3_ACCESS_KEY": "test",
        "S3_SECRET_KEY": "test",
        "S3_BUCKET": "test",
        "S3_REGION": "us-east-1",
        "S3_STORAGE_CLASS": "foobar",
        "S3_ATTRIBUTES": '["test", "example"]',
    }
    for unit_ip in await get_unit_ips(django_app.name):
        env = {
            k: v
            for k, v in requests.get(f"http://{unit_ip}:8000/environ", timeout=5).json().items()
            if k.startswith("S3_")
        }
        print(env)
        assert expected_env == env
