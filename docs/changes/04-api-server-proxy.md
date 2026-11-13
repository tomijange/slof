# 4. Reaching the cluster through the API server proxy

**Compared to GOXN:** `oxn` reaches the steering sidecars, Prometheus, Jaeger and the Locust master through the Kubernetes API server, so it runs anywhere `kubectl` works instead of only inside the cluster network.

## Summary

GOXN sent HTTP requests straight to pod IPs and ClusterIPs. That only worked from a machine with a route into the cluster network, so users needed port forwards or a VPN such as kubevpn. This change sends those requests through the API server proxy, authenticated with the kubeconfig. It also makes failed `tc` commands in the steering sidecar visible.

| | GOXN | After this change |
|---|---|---|
| Control and observation traffic | Direct HTTP to pod and cluster IPs | `<api-server>/api/v1/namespaces/<ns>/{pods,services}/<name>:<port>/proxy/<path>` |
| Where `oxn` runs | Inside the cluster network, or with `forward.ps1` or kubevpn | Anywhere `kubectl` works |
| Load traffic | Locust to the target's ClusterIP | Unchanged |
| A `tc` command that fails in the sidecar | Looks like a success | Logged as an error |

## The cluster proxy

**Now documented in:** [Deployments: reaching the cluster network](../deployments.md#reaching-the-cluster-network)

`oxn/orchestration/cluster_proxy.py` builds proxy URLs for pods and services. It also creates `requests` sessions that authenticate with the credentials from the kubeconfig. The orchestrator creates one `ClusterProxy` and shares it with four clients:

- The `SteeringController`, for `tc` commands to the sidecar on port 5000
- `Prometheus`
- `Jaeger`
- The Locust master's stats endpoint

Details:

- **Expiring tokens.** The bearer token is read again for every request, because tokens from exec plugins can expire during a long run.
- **Environment settings.** `trust_env` is turned off, so netrc and `REQUESTS_CA_BUNDLE` cannot override the kubeconfig's TLS settings.
- **Load traffic.** Locust still sends its load directly to the target's ClusterIP from inside the cluster. If the load went through the proxy, the API server would become part of the measured path.

**Why.** Experiments run against a remote cluster, often from a laptop. The repository showed the workarounds GOXN needed: `forward.ps1` with `kubectl port-forward` calls, and `kubevpn.exe` in `.gitignore`. Through the API server proxy, `oxn` needs no tunnel, including from macOS.

**What this breaks.** The kubeconfig user needs access to `pods/proxy` and `services/proxy`. `forward.ps1` is removed, and `kubevpn.exe` is no longer in `.gitignore`.

## Steering controller cleanup

**Now documented in:** [Experiments: treatments](../experiments.md#treatments)

The six `send_tc_*` methods of the `SteeringController` each held a copy of the same request code. They now share `_send_tc`, which:

- Goes through the cluster proxy.
- Sets a 30 s timeout.
- Logs an error when the steering container answers with HTTP 200 but its JSON `status` is not `ok`.

**Why.** Before, a `tc` command that failed inside the pod looked like a success. A treatment could then report that it injected a delay that never happened.

## Tests

`test_cluster_proxy.py` covers the URLs, the TLS and token handling, that the steering controller, Prometheus, Jaeger and the Locust stats go through the proxy, and that failed `tc` commands are logged.

## Known limitations

Nothing is left open by this change.
