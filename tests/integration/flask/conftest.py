# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Fixtures for flask charm integration tests."""

import io
import json
import os
import pathlib
import shutil
import zipfile

import pytest
import pytest_asyncio
import yaml
from juju.application import Application
from juju.model import Model
from pytest import Config, FixtureRequest
from pytest_operator.plugin import OpsTest

PROJECT_ROOT = pathlib.Path(__file__).parent.parent.parent.parent


@pytest.fixture(autouse=True)
def cwd():
    return os.chdir(PROJECT_ROOT / "examples/flask")


@pytest.fixture(scope="module", name="flask_app_image")
def fixture_flask_app_image(pytestconfig: Config):
    """Return the --flask-app-image test parameter."""
    flask_app_image = pytestconfig.getoption("--flask-app-image")
    if not flask_app_image:
        raise ValueError("the following arguments are required: --flask-app-image")
    return flask_app_image


@pytest.fixture(scope="module", name="test_flask_image")
def fixture_test_flask_image(pytestconfig: Config):
    """Return the --test-flask-image test parameter."""
    test_flask_image = pytestconfig.getoption("--test-flask-image")
    if not test_flask_image:
        raise ValueError("the following arguments are required: --test-flask-image")
    return test_flask_image


@pytest.fixture(scope="module", name="test_db_flask_image")
def fixture_test_db_flask_image(pytestconfig: Config):
    """Return the --test-flask-image test parameter."""
    test_flask_image = pytestconfig.getoption("--test-db-flask-image")
    if not test_flask_image:
        raise ValueError("the following arguments are required: --test-db-flask-image")
    return test_flask_image


@pytest_asyncio.fixture(scope="module", name="model")
async def fixture_model(ops_test: OpsTest) -> Model:
    """Return the current testing juju model."""
    assert ops_test.model
    return ops_test.model


@pytest.fixture(scope="module", name="external_hostname")
def external_hostname_fixture() -> str:
    """Return the external hostname for ingress-related tests."""
    return "juju.test"


@pytest.fixture(scope="module", name="traefik_app_name")
def traefik_app_name_fixture() -> str:
    """Return the name of the traefik application deployed for tests."""
    return "traefik-k8s"


@pytest.fixture(scope="module", name="prometheus_app_name")
def prometheus_app_name_fixture() -> str:
    """Return the name of the prometheus application deployed for tests."""
    return "prometheus-k8s"


@pytest.fixture(scope="module", name="loki_app_name")
def loki_app_name_fixture() -> str:
    """Return the name of the prometheus application deployed for tests."""
    return "loki-k8s"


@pytest.fixture(scope="module", name="grafana_app_name")
def grafana_app_name_fixture() -> str:
    """Return the name of the grafana application deployed for tests."""
    return "grafana-k8s"


def inject_venv(charm: pathlib.Path | str, src: pathlib.Path | str):
    """Inject a Python library into the charm venv directory inside a charm file."""
    zip_file = zipfile.ZipFile(charm, "a")
    src = pathlib.Path(src)
    if not src.exists():
        raise FileNotFoundError(f"Python library {src} not found")
    for file in src.rglob("*"):
        if "__pycache__" in str(file):
            continue
        rel_path = file.relative_to(src.parent)
        zip_file.write(file, os.path.join("venv/", rel_path))


@pytest_asyncio.fixture(scope="module", name="charm_file")
async def charm_file_fixture(pytestconfig: pytest.Config, ops_test: OpsTest) -> pathlib.Path:
    """Get the existing charm file."""
    charm_file = pytestconfig.getoption("--charm-file")
    if not charm_file:
        charm_file = await ops_test.build_charm(PROJECT_ROOT / "examples/flask")
    elif charm_file[0] != "/":
        charm_file = PROJECT_ROOT / charm_file
    inject_venv(charm_file, PROJECT_ROOT / "xiilib")
    return pathlib.Path(charm_file).absolute()


@pytest_asyncio.fixture(scope="module", name="build_charm")
async def build_charm_fixture(charm_file: str) -> str:
    """Build the charm and injects additional configurations into config.yaml.

    This fixture is designed to simulate a feature that is not yet available in charmcraft that
    allows for the modification of charm configurations during the build process.
    Three additional configurations, namely foo_str, foo_int, foo_dict, foo_bool,
    and application_root will be appended to the config.yaml file.
    """
    charm_zip = zipfile.ZipFile(charm_file, "r")
    with charm_zip.open("config.yaml") as file:
        config = yaml.safe_load(file)
    config["options"].update(
        {
            "foo_str": {"type": "string"},
            "foo_int": {"type": "int"},
            "foo_bool": {"type": "boolean"},
            "foo_dict": {"type": "string"},
            "application_root": {"type": "string"},
        }
    )
    modified_config = yaml.safe_dump(config)
    new_charm = io.BytesIO()
    with zipfile.ZipFile(new_charm, "w") as new_charm_zip:
        for item in charm_zip.infolist():
            if item.filename == "config.yaml":
                new_charm_zip.writestr(item, modified_config)
            else:
                with charm_zip.open(item) as file:
                    data = file.read()
                new_charm_zip.writestr(item, data)
    charm_zip.close()
    charm = pathlib.Path("flask-k8s_ubuntu-22.04-amd64_modified.charm").absolute()
    with open(charm, "wb") as new_charm_file:
        new_charm_file.write(new_charm.getvalue())
    return str(charm)


@pytest_asyncio.fixture(scope="module", name="flask_app")
async def flask_app_fixture(build_charm: str, model: Model, test_flask_image: str):
    """Build and deploy the flask charm."""
    app_name = "flask-k8s"

    resources = {
        "flask-app-image": test_flask_image,
        "statsd-prometheus-exporter-image": "prom/statsd-exporter",
    }
    app = await model.deploy(
        build_charm, resources=resources, application_name=app_name, series="jammy"
    )
    await model.wait_for_idle(raise_on_blocked=True)
    return app


@pytest_asyncio.fixture(scope="module", name="flask_db_app")
async def flask_db_app_fixture(build_charm: str, model: Model, test_db_flask_image: str):
    """Build and deploy the flask charm with test-db-flask image."""
    app_name = "flask-k8s"

    resources = {
        "flask-app-image": test_db_flask_image,
        "statsd-prometheus-exporter-image": "prom/statsd-exporter",
    }
    app = await model.deploy(
        build_charm, resources=resources, application_name=app_name, series="jammy"
    )
    await model.wait_for_idle()
    return app


@pytest_asyncio.fixture(scope="module", name="traefik_app")
async def deploy_traefik_fixture(
    model: Model,
    flask_app,  # pylint: disable=unused-argument
    traefik_app_name: str,
    external_hostname: str,
):
    """Deploy traefik."""
    app = await model.deploy(
        "traefik-k8s",
        application_name=traefik_app_name,
        channel="edge",
        trust=True,
        config={
            "external_hostname": external_hostname,
            "routing_mode": "subdomain",
        },
    )
    await model.wait_for_idle(raise_on_blocked=True)

    return app


@pytest_asyncio.fixture(scope="module", name="prometheus_app")
async def deploy_prometheus_fixture(
    model: Model,
    prometheus_app_name: str,
):
    """Deploy prometheus."""
    app = await model.deploy(
        "prometheus-k8s",
        application_name=prometheus_app_name,
        channel="1.0/stable",
        revision=129,
        series="focal",
        trust=True,
    )
    await model.wait_for_idle(raise_on_blocked=True)

    return app


@pytest_asyncio.fixture(scope="module", name="loki_app")
async def deploy_loki_fixture(
    model: Model,
    loki_app_name: str,
):
    """Deploy loki."""
    app = await model.deploy(
        "loki-k8s", application_name=loki_app_name, channel="latest/stable", trust=True
    )
    await model.wait_for_idle(raise_on_blocked=True)

    return app


@pytest_asyncio.fixture(scope="module", name="cos_apps")
async def deploy_cos_fixture(
    model: Model,
    loki_app,  # pylint: disable=unused-argument
    prometheus_app,  # pylint: disable=unused-argument
    grafana_app_name: str,
):
    """Deploy the cos applications."""
    cos_apps = await model.deploy(
        "grafana-k8s",
        application_name=grafana_app_name,
        channel="1.0/stable",
        revision=82,
        series="focal",
        trust=True,
    )
    await model.wait_for_idle(status="active")
    return cos_apps


async def model_fixture(ops_test: OpsTest) -> Model:
    """Provide current test model."""
    assert ops_test.model
    model_config = {"logging-config": "<root>=INFO;unit=DEBUG"}
    await ops_test.model.set_config(model_config)
    return ops_test.model


@pytest_asyncio.fixture(scope="module", name="get_unit_ips")
async def fixture_get_unit_ips(ops_test: OpsTest):
    """Return an async function to retrieve unit ip addresses of a certain application."""

    async def get_unit_ips(application_name: str):
        """Retrieve unit ip addresses of a certain application.

        Returns:
            a list containing unit ip addresses.
        """
        _, status, _ = await ops_test.juju("status", "--format", "json")
        status = json.loads(status)
        units = status["applications"][application_name]["units"]
        return tuple(
            unit_status["address"]
            for _, unit_status in sorted(units.items(), key=lambda kv: int(kv[0].split("/")[-1]))
        )

    return get_unit_ips


@pytest_asyncio.fixture
async def update_config(model: Model, request: FixtureRequest, flask_app: Application):
    """Update the flask application configuration.

    This fixture must be parameterized with changing charm configurations.
    """
    orig_config = {k: v.get("value") for k, v in (await flask_app.get_config()).items()}
    request_config = {k: str(v) for k, v in request.param.items()}
    await flask_app.set_config(request_config)
    await model.wait_for_idle(apps=[flask_app.name])

    yield request_config

    await flask_app.set_config(
        {k: v for k, v in orig_config.items() if k in request_config and v is not None}
    )
    await flask_app.reset_config([k for k in request_config if orig_config[k] is None])
    await model.wait_for_idle(apps=[flask_app.name])
