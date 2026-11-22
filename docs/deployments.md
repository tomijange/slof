# Deployments

The `deployment` section of an experiment spec describes the SUE and its observability stack as an ordered list of Helm releases, manifest folders and images to build. `oxn` applies it around every experiment run, so each run starts from a clean cluster. It is defined by `DeploymentDescription`, part of the experiment spec model in `oxn/models/experiment_spec.py`.

## Shipped setups

Every spec in `experiments/` has a `deployment` section, in one of three setups. A comment at the top of each spec says what it measures and which setup each variant uses.

| Setup | Specs and variants | Deploys |
|---|---|---|
| In-memory Jaeger | `test.yml`, `recommendation_k8_fault.yml`, `recommendation_k8_minimal.yml`, `storage=memory` of `recommendation_k8_sampling.yml` and `recommendation_k8_metric_export.yml` | The SUE with `values_opentelemetry_demo.yaml` |
| Elasticsearch | `storage=elasticsearch` of the same two specs, `mesh=none` of `recommendation_k8_scrape_mesh.yml` | `k8s/elasticsearch/`, then the SUE with `values_opentelemetry_demo_persistence.yaml` |
| Istio | `mesh=istio` of `recommendation_k8_scrape_mesh.yml` | Istio in `istio-system`, sidecar injection on `system-under-evaluation`, then the Elasticsearch setup |

None of them deploys Prometheus or Kepler, so run `oxn setup` first.

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

For a spec with a [matrix](experiments.md#matrix) whose variants deploy different things, pick one with `--only`, for example `oxn deploy experiments/x.yml --only storage=elasticsearch`.

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
          values: [../deployments/values/values_opentelemetry_demo.yaml]
          set: {components.recommendation.resources.limits.cpu: 500m}
          timeout: 15m               # optional, default 15m
      - manifests:
          paths: [../k8s/elasticsearch/]
          namespace: system-under-evaluation
          wait_for: [deployment/elasticsearch]
          timeout: 15m               # optional, default 15m
      - image:
          name: slof.local/recommendation-rust:0.1.0
          context: ../images/recommendation-rust
          dockerfile: ../images/recommendation-rust/Dockerfile   # optional, default the Dockerfile in context
          build_args: {PROFILE: release}                        # optional
          delivery: import           # or push, the default
```

Relative paths in `values`, `paths`, `context` and `dockerfile` are resolved against the folder of the spec file, so this spec lives in `experiments/`.

## Images

An `image` step builds an image with `docker buildx build` and makes it available to the cluster. It does not change any workload: the [`deployment_image` treatment](experiments.md#built-in-treatments) or the values of a Helm step make pods use it. A step's `name` needs a tag other than `latest`, because Kubernetes pulls `latest` on every start.

| `delivery` | What happens | Needs |
|---|---|---|
| `push` | Builds for `platforms`, by default the platforms of the nodes, and pushes to the registry in `name` | A registry the nodes can pull from, and `docker login` to it |
| `import` | Builds one archive per platform of the nodes and streams it into the containerd of every node | Privileged pods in `kube-system`, MicroK8s, k3s or containerd at `/run/containerd` |

The builds cross-compile or emulate, so an image for amd64 nodes builds on an arm64 Mac. For `import`, `oxn` starts a busybox pod with `hostPID` and `privileged` on each node, runs `ctr images import` of the node's containerd in the node's mount namespace with the archive on stdin through `kubectl exec`, and deletes the pod. The pods pull `busybox`, so the nodes need to reach Docker Hub.

Deploying again builds again, with the build cache of Docker, so repeated runs take seconds. Teardown keeps the image, in the registry or on the nodes.

## What deploy and teardown do

**Deploy** creates the listed namespaces and then runs the steps in order. Image steps build and deliver their image, see [Images](#images). Helm steps use `helm upgrade --install --wait`, so deploying again upgrades in place. The OpenTelemetry Demo chart does not support this across chart versions, so tear down before you change its version.

**Teardown** does the following:

1. Runs the steps in reverse order. Image steps are skipped.
2. Deletes the PVCs labelled with each uninstalled Helm release's name.
3. Deletes the namespaces listed under `namespaces`.

The `oxn-external-monitoring` namespace is not listed, so Kepler stays in place. The CRDs from the Prometheus chart also stay, because Helm does not remove them on uninstall.

## Small clusters

The specs request about 35 GiB of memory. To fit the SUE on a smaller cluster, add `deployments/values/values_opentelemetry_demo_local.yaml` to the `values` of the `astronomy-shop` release in your spec, which brings that down to about 6 GiB. Do not use the numbers from such a run as experiment results, because the resources differ.

## Reaching the cluster network

`oxn` reaches the steering containers, Prometheus, Jaeger and the Locust master through the proxy of the Kubernetes API server, so it runs anywhere `kubectl` works, including from macOS. The credentials in your kubeconfig need access to `pods/proxy` and `services/proxy`.

The load itself does not take this path. Locust runs inside the cluster and sends its requests directly to the target's ClusterIP, so the API server does not become part of the measured path.
