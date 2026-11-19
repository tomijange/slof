"""
Prometheus metrics of the in-cluster Locust, at /metrics of the master's web UI

oxn ships this file with every in-cluster Locust and adds it to the locust files of master and workers. It defines no
users. The master reports the requests of all workers:

- locust_requests_total and locust_request_failures_total: cumulative counters per request name and method. Locust
  counts connection errors and HTTP status codes from 400 on as failures.
- locust_request_duration_seconds: a cumulative histogram per request name and method, with the bucket edges of the
  OpenTelemetry default, as the frontend's http_server_request_duration_seconds. The share of requests below an SLO
  threshold can so be compared between what the users saw and what the frontend measured.
- locust_users: the number of running users.

The counters start at zero with every master, so with every run.
"""

from flask import Response

from locust import events

BUCKETS_MS = (5, 10, 25, 50, 75, 100, 250, 500, 750, 1000, 2500, 5000, 7500, 10000)
"""Upper bucket edges in milliseconds. Locust rounds response times above 100 ms to 10 ms and above 1000 ms to 100 ms,
which keeps these edges exact"""


def _escape(value) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _labels(**labels) -> str:
    return "{" + ",".join(f'{key}="{_escape(value)}"' for key, value in labels.items()) + "}"


def render(environment) -> str:
    """The metrics in the Prometheus text format"""
    requests = ["# HELP locust_requests_total Requests sent", "# TYPE locust_requests_total counter"]
    failures = [
        "# HELP locust_request_failures_total Requests that failed",
        "# TYPE locust_request_failures_total counter",
    ]
    durations = [
        "# HELP locust_request_duration_seconds Response times of the requests",
        "# TYPE locust_request_duration_seconds histogram",
    ]
    runner = environment.runner
    for entry in runner.stats.entries.values() if runner is not None else []:
        labels = {"name": entry.name, "method": entry.method}
        requests.append(f"locust_requests_total{_labels(**labels)} {entry.num_requests}")
        failures.append(f"locust_request_failures_total{_labels(**labels)} {entry.num_failures}")
        times = sorted(entry.response_times.items())
        for edge in BUCKETS_MS:
            count = sum(n for time, n in times if time <= edge)
            durations.append(f"locust_request_duration_seconds_bucket{_labels(**labels, le=edge / 1000)} {count}")
        total = sum(n for _, n in times)
        durations.append(f"locust_request_duration_seconds_bucket{_labels(**labels, le='+Inf')} {total}")
        durations.append(f"locust_request_duration_seconds_sum{_labels(**labels)} {entry.total_response_time / 1000}")
        durations.append(f"locust_request_duration_seconds_count{_labels(**labels)} {total}")
    users = [
        "# HELP locust_users Running users",
        "# TYPE locust_users gauge",
        f"locust_users {runner.user_count if runner is not None else 0}",
    ]
    return "\n".join(requests + failures + durations + users) + "\n"


@events.init.add_listener
def _add_metrics_route(environment, **_kwargs):
    # only the master has a web UI, and only it knows the requests of all workers
    if environment.web_ui is None:
        return

    @environment.web_ui.app.route("/metrics")
    def metrics():
        return Response(render(environment), mimetype="text/plain; version=0.0.4; charset=utf-8")
