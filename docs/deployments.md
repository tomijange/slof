# Deployments

The `deployment` section of an experiment spec describes the SUE and its observability stack as an ordered list of Helm releases and manifest folders. `oxn` applies it around every experiment run, so each run starts from a clean cluster. It is defined by `DeploymentDescription`, part of the experiment spec model in `oxn/models/experiment_spec.py`.

## Shipped setups

Two specs in `experiments/` have a `deployment` section:

| Spec | Deploys |
|---|---|
| `test.yml` | The SUE with in-memory Jaeger. Prometheus and Kepler stay in place, so run `oxn setup` first |
| `debug.yml` | Prometheus and the SUE with in-memory Jaeger. Its teardown also removes Prometheus |

The `recommendation_*` specs have no `deployment` section, so they expect the SUE to be running already. They also still use service and metric names from older chart versions, such as `jaeger-query`, so update them before you run them against the versions deployed here.

Helm values live in `deployments/values/`, including the ones for the Elasticsearch persistence setup.

## Deploy as part of an experiment

`oxn` deploys before every run and tears down afterwards. To keep the SUE running after the experiment, for example to inspect it:

```bash
oxn <spec> --report reports/ --keep-sue
```

Specs without a `deployment` section expect the SUE to be running already.

## Deploy and tear down by hand

`oxn deploy` and `oxn teardown` apply and remove the `deployment` section of a spec without running the experiment:

```bash
oxn deploy experiments/test.yml
oxn teardown experiments/test.yml
```

The Makefile has shortcuts: `make deploy-sue` and `make teardown-sue`, with `SPEC=<spec>` to pick another spec than `experiments/test.yml`.

## Section format

```yaml
experiment:
  orchestrator: kubernetes
  deployment:
    namespaces:                      # owned by the experiment and deleted on teardown
      - name: system-under-evaluation
        labels: {istio-injection: enabled}
    steps:
      - helm:
          release: astronomy-shop
          chart: opentelemetry-demo
          repo: https://open-telemetry.github.io/opentelemetry-helm-charts
          version: 0.42.6
          namespace: system-under-evaluation
          values: [deployments/values/values_opentelemetry_demo.yaml]
          set: {components.recommendation.resources.limits.cpu: 500m}
          timeout: 15m               # optional, default 15m
      - manifests:
          paths: [k8s/elasticsearch/]
          namespace: system-under-evaluation
          wait_for: [deployment/elasticsearch]
          timeout: 15m               # optional, default 15m
```

## What deploy and teardown do

**Deploy** creates the listed namespaces and then runs the steps in order. Helm steps use `helm upgrade --install --wait`, so deploying again upgrades in place. The OpenTelemetry Demo chart does not support this across chart versions, so tear down before you change its version.

**Teardown** does the following:

1. Runs the steps in reverse order.
2. Deletes the PVCs labelled with each uninstalled Helm release's name.
3. Deletes the namespaces listed under `namespaces`.

The `oxn-external-monitoring` namespace is not listed, so Kepler stays in place. The CRDs from the Prometheus chart also stay, because Helm does not remove them on uninstall.

## Small clusters

The specs request about 35 GiB of memory. To fit the SUE on a smaller cluster, add `deployments/values/values_opentelemetry_demo_local.yaml` to the `values` of the `astronomy-shop` release in your spec, which brings that down to about 6 GiB. Do not use the numbers from such a run as experiment results, because the resources differ.

## Reaching the cluster network

`oxn` reaches the steering containers, Prometheus, Jaeger and the Locust master through the proxy of the Kubernetes API server, so it runs anywhere `kubectl` works, including from macOS. The credentials in your kubeconfig need access to `pods/proxy` and `services/proxy`.

The load itself does not take this path. Locust runs inside the cluster and sends its requests directly to the target's ClusterIP, so the API server does not become part of the measured path.
