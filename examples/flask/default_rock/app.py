# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
from flask import Flask

app = Flask(__name__)
app.config.from_prefixed_env()

hello_page = """\
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Welcome to flask-k8s Charm</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 0;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            background: #f5f5f5;
        }
        .container {
            text-align: center;
            padding: 2em;
            background: #fff;
            border-radius: 8px;
            box-shadow: 0px 0px 10px rgba(0, 0, 0, 0.1);
        }
        h1 {
            color: #333;
            font-size: 2em;
        }
        h2 {
            color: #666;
            margin-top: 1em;
        }
        p {
            color: #777;
            line-height: 1.5;
            margin-top: 1em;
        }
        code {
            background-color: #f8f9fa;
            border-radius: 5px;
            padding: 0.2em 0.4em;
            margin: 0;
            font-size: 1em;
        }
        a {
            color: #3498db;
            text-decoration: none;
        }
        a:hover {
            text-decoration: underline;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Welcome to flask-k8s Charm</h1>
        <p>Congratulations! You've successfully deployed the flask-k8s charm.</p>
        <h2>What's next?</h2>
        <p>To supply your own image, you can use the following command:</p>
        <code>juju attach-resource &lt;flask-k8s-name&gt; flask-app-image=&lt;flask-app-image&gt;</code>
        <p>For more information and further guidance, please visit the <a referrerpolicy="no-referrer" href="https://charmhub.io/flask-k8s/docs">flask-k8s documentation</a>.</p>
    </div>
</body>
</html>
"""


@app.route('/', defaults={'_': ''})
@app.route("/<path:_>")
def hello(_):
    return hello_page
