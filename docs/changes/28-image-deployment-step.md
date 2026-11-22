# 28. Image deployment step

**Compared to GOXN:** a `deployment` section can build container images with an `image` step. The step pushes the image to a registry, or imports it into the containerd of every node, so the cluster needs no registry. A spec can bring the code of a service it compares, and every run builds it from the folder next to the spec.

## Summary

In GOXN, the SUE on Kubernetes only runs images from registries. An image built from local code has to be built, pushed or loaded onto the nodes by hand before every experiment, for the platform of the nodes. This change makes that a deployment step, next to `helm` and `manifests`. It goes together with the `deployment_image` treatment of [change 27](27-deployment-image-treatment.md), which makes a deployment use the image.

| | GOXN | After this change |
|---|---|---|
| Deployment steps | `helm`, `manifests` ([change 3](03-deployment-section.md)) | `helm`, `manifests`, `image` |
| Local images | Built and delivered by hand | Built by `docker buildx` for the platforms of the nodes, pushed or imported on every deploy |
| Cluster without a registry | Images loaded onto the nodes by hand | `delivery: import` streams the image into the containerd of each node |
| Tools | `helm`, `kubectl` | Also `docker` with buildx, only for specs with an `image` step |

## The image step

**Now documented in:** [Deployments](../deployments.md#images)

`ImageBuild` in `oxn/models/experiment_spec.py` describes the step:

```yaml
deployment:
  steps:
    - image:
        name: slof.local/recommendation-rust:0.1.0
        context: images/recommendation-rust
        dockerfile: images/recommendation-rust/Dockerfile   # optional
        build_args: {PROFILE: release}                     # optional
        delivery: import                                   # or push, the default
        platforms: [linux/amd64]                           # optional, only for push
```

| Field | Meaning |
|---|---|
| `name` | The reference the pods use. It needs a tag other than `latest`, or a digest |
| `context`, `dockerfile` | The folder to build and the Dockerfile, resolved against the folder of the spec as since [change 26](26-spec-relative-paths.md) |
| `build_args` | Passed as `--build-arg` |
| `delivery` | `push` or `import` |
| `platforms` | For `push`, the platforms to build. By default the platforms of the nodes. Not allowed with `import`, which builds for each node's platform |

`Deployment.deploy` reads the platforms of the nodes from `nodeInfo`, as `<operatingSystem>/<architecture>`. With `push` it runs `docker buildx build --platform <platforms> --output type=registry`, so the nodes pull the image from the registry in `name`. With `import`, it builds one archive per platform with `--output type=docker,dest=<file>` and imports it into every node of that platform. `teardown` skips image steps and keeps the image. `_require_tools` asks for `docker`, and also for `kubectl` with `import`.

The schema lists `image` as a third kind of step, so editors complete its fields.

**Why.** The image tag alone does not say which code an experiment ran, and a hand-built image is easy to forget to rebuild. Building in the deploy ties the image to the code in the spec's folder at the time of the run. Docker's build cache makes rebuilding fast when the code has not changed. Building for the nodes' platforms lets an arm64 laptop build for amd64 nodes without extra settings. A `latest` tag is rejected because Kubernetes pulls `latest` on every pod start, which fails for an imported image and makes runs depend on the registry.

## Importing into the nodes

**Now documented in:** [Deployments](../deployments.md#images)

For each node, `Deployment._import_on_node`:

1. Creates a pod `oxn-image-import-<random>` in `kube-system`, pinned to the node with `nodeName`, with `hostPID`, a privileged `docker.io/library/busybox:1.37.0` container and a toleration for every taint.
2. Waits up to 120 seconds for it to be ready.
3. Runs `nsenter -t 1 -m -- sh -c <script>` in it through `kubectl exec --stdin`, with the archive as stdin. The script runs in the mount namespace of the node, finds the containerd socket of MicroK8s, k3s or plain containerd, and runs that containerd's `ctr --namespace k8s.io images import -`.
4. Deletes the pod, also when a step before failed.

To send a file as stdin, `run_command` takes an `input_path`. `CommandRunner` is now `Callable[..., str]`.

**Why.** Single-node lab clusters such as MicroK8s and k3s often have no registry. A registry in the cluster needs insecure-registry settings on both the build machine and the nodes. Importing through a pod only needs what `oxn` already uses: the API server and `kubectl`. Each node gets the image for its own architecture. The `k8s.io` namespace is where the kubelet looks for images, so pods with `imagePullPolicy: IfNotPresent` start from the imported image without pulling.

**What this breaks.** Own code that passes a `run` function to `Deployment` has to accept the keyword `input_path`.

## Tests

`oxn/tests/unit/test_deployment.py` checks that:

- `name` needs a pinned tag or a digest,
- `platforms` is rejected with `import`,
- `context` and `dockerfile` are resolved against the spec's folder,
- `push` builds once for the nodes' platforms, or for `platforms`, with the build args,
- `import` builds one archive per platform, starts a privileged pod with `hostPID` on every node, streams the matching archive into it and deletes the pod,
- the pod is deleted when the import fails,
- teardown runs no command for an image step,
- a missing `docker` stops the deploy.

`python -m pytest oxn/tests/unit` reports 278 passing tests, together with [change 27](27-deployment-image-treatment.md#tests), and the 3 failures [change 18](18-formatting-and-type-fixes.md#known-limitations) lists. The import also ran against a single-node MicroK8s cluster with an amd64 node, building on an arm64 Mac. A pod with `imagePullPolicy: Never` then started from the imported image.

## Known limitations

| Limitation | Status |
|---|---|
| `push` is only covered by unit tests, not by a run against a registry. Building several platforms at once needs a buildx builder that supports it, such as Docker Desktop with the containerd image store. | Open |
| `import` is tested on MicroK8s only. The paths for k3s and plain containerd are in the script but have not run. Docker Engine and CRI-O nodes are not supported. | Open |
| `import` needs privileged pods in `kube-system`, and the nodes have to pull `busybox` from Docker Hub. | By design |
| Every deploy builds and imports again. A cached build takes seconds, the import streams the whole archive through the API server. | Open |
| Images stay in the registry or on the nodes after teardown, so imported images pile up on the nodes until they are removed with `ctr`. | By design |
| Nodes that join after the deploy do not have an imported image. | Open |
| A build has no timeout. | Open |
