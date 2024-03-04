# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import os
import time
from urllib.parse import urlparse

import psycopg
import pymysql
import pymysql.cursors
from flask import Flask, g, jsonify, request

app = Flask(__name__)
app.config.from_prefixed_env()


def get_mysql_database():
    """Get the mysql db connection."""
    if "mysql_db" not in g:
        if "MYSQL_DB_CONNECT_STRING" in os.environ:
            uri_parts = urlparse(os.environ["MYSQL_DB_CONNECT_STRING"])
            g.mysql_db = pymysql.connect(
                host=uri_parts.hostname,
                user=uri_parts.username,
                password=uri_parts.password,
                database=uri_parts.path[1:],
                port=uri_parts.port,
            )
        else:
            return None
    return g.mysql_db


def get_postgresql_database():
    """Get the postgresql db connection."""
    if "postgresql_db" not in g:
        if "POSTGRESQL_DB_CONNECT_STRING" in os.environ:
            g.postgresql_db = psycopg.connect(
                conninfo=os.environ["POSTGRESQL_DB_CONNECT_STRING"],
            )
        else:
            return None
    return g.postgresql_db


@app.teardown_appcontext
def teardown_database(_):
    """Tear down databases connections."""
    mysql_db = g.pop("mysql_db", None)
    if mysql_db is not None:
        mysql_db.close()
    postgresql_db = g.pop("postgresql_db", None)
    if postgresql_db is not None:
        postgresql_db.close()


@app.route("/")
def hello_world():
    return "Hello, World!"


@app.route("/sleep")
def sleep():
    duration_seconds = int(request.args.get("duration"))
    time.sleep(duration_seconds)
    return ""


@app.route("/config/<config_name>")
def config(config_name: str):
    return jsonify(app.config.get(config_name))


@app.route("/mysql/status")
def mysql_status():
    """Mysql status endpoint."""
    if database := get_mysql_database():
        with database.cursor() as cursor:
            sql = "SELECT version()"
            cursor.execute(sql)
            cursor.fetchone()
            return "SUCCESS"
    return "FAIL"


@app.route("/postgresql/status")
def postgresql_status():
    """Postgresql status endpoint."""
    if database := get_postgresql_database():
        with database.cursor() as cursor:
            sql = "SELECT version()"
            cursor.execute(sql)
            cursor.fetchone()
            return "SUCCESS"
    return "FAIL"


@app.route("/env")
def get_env():
    """Return environment variables"""
    return jsonify(dict(os.environ))
