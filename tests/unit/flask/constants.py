DEFAULT_LAYER = {
    "services": {
        "flask": {
            "override": "replace",
            "startup": "enabled",
            "command": f"/bin/python3 -m gunicorn -c /flask/gunicorn.conf.py app:app",
            "after": ["statsd-exporter"],
            "user": "_daemon_",
        },
        "statsd-exporter": {
            "override": "merge",
            "command": (
                "/bin/statsd_exporter --statsd.mapping-config=/statsd-mapping.conf "
                "--statsd.listen-udp=localhost:9125 "
                "--statsd.listen-tcp=localhost:9125"
            ),
            "summary": "statsd exporter service",
            "startup": "enabled",
            "user": "_daemon_",
        },
    }
}
