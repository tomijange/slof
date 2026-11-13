# GOXN

GOXN (**G**reen **O**bservability e**X**periment e**N**gine) is a framework for running green observability experiments and comparing design decisions. It is a fork of [OXN](https://github.com/nymphbox/oxn).

Experiments are YAML files, so they can be shared, versioned and repeated. GOXN automates the process from setting up the system under experiment to collecting the data and writing a report.

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

The documentation is published at <https://julianlegler.github.io/goxn/>. To build it locally, run `pip install -r docs/requirements.txt` and `make docs`, then open `docs/_build/html/index.html`.

- [Getting started](docs/getting-started.md)
- [Deployments](docs/deployments.md)
- [Experiments](docs/experiments.md)
- [Architecture](docs/architecture.md)
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
