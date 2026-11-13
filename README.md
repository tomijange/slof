# SLOF

SLOF is a framework for experiment-driven evaluation of trade-offs between service level objectives (SLOs) and sustainability. It is a fork of [GOXN](https://github.com/JulianLegler/goxn) (**G**reen **O**bservability e**X**periment e**N**gine), which in turn builds on [OXN](https://github.com/nymphbox/oxn).

Experiments are YAML files, so they can be shared, versioned and repeated. SLOF automates the process from setting up the system under experiment to collecting the data and writing a report.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

oxn setup
mkdir -p reports
oxn experiments/test.yml --report reports/
```

`oxn setup` guides you through installing OpenEBS, Prometheus and Kepler on your cluster. The experiment spec then deploys the system under experiment and removes it afterwards.

This needs Python 3.10 or newer, `kubectl` and Helm. The [getting started guide](docs/getting-started.md) has the details.

## Documentation

The documentation is published at <https://tomijange.github.io/slof/>. To build it locally, run `pip install -r docs/requirements.txt` and `make docs`, then open `docs/_build/html/index.html`.

- [Getting started](docs/getting-started.md)
- [Deployments](docs/deployments.md)
- [Experiments](docs/experiments.md)
- [Experiment design](docs/experiment-design.md): what the shipped experiments measure and which to compare
- [Architecture](docs/architecture.md)
- [Changes](docs/changes/index.md): what changed compared to GOXN, and why, one page per change
- [Tool guides](docs/README.md#tools): how to deploy OpenEBS, Prometheus, Grafana, Kepler, the OpenTelemetry Demo, the OpenTelemetry Collector, Jaeger, Elasticsearch, Istio and Locust with Helm

## Repository layout

| Path           | Contents                                                |
| -------------- | ------------------------------------------------------- |
| `oxn/`         | The experiment engine                                   |
| `experiments/` | Experiment specs, some including what they deploy       |
| `deployments/` | Helm values and the Grafana dashboard                   |
| `k8s/`         | Elasticsearch manifests                                 |
| `locust/`      | Load scenarios and the templates for the Locust pods    |
| `docs/`        | Documentation                                           |

To process results further, see the [GOXN replication package](https://github.com/JulianLegler/goxn-replication-package).
