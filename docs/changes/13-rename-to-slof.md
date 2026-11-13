# 13. Rename to SLOF

**Compared to GOXN:** the project is called SLOF and lives at <https://github.com/tomijange/slof>, with its documentation at <https://tomijange.github.io/slof/>. The Python package and the `oxn` command keep their names.

## Summary

The fork moved to its own repository and took the name of the thesis it serves: SLOF, experiment-driven evaluation of SLO and sustainability trade-offs. Text that describes the project as it is now says SLOF. Text that compares to the baseline, such as the change pages and the history of the shipped specs, still says GOXN, because it means GOXN.

| Area | GOXN | After this change |
|---|---|---|
| Name | GOXN | SLOF |
| Repository | `github.com/JulianLegler/goxn` | `github.com/tomijange/slof` |
| Documentation site | `julianlegler.github.io/goxn` | `tomijange.github.io/slof` |
| Python package and command | `oxn` | `oxn`, unchanged |

## Name and links

**Now documented in:** [Overview](../index.md), [Tools](../index.md#tools)

- The README, the docs title and the Sphinx `project`, `html_title` and `html_baseurl` say SLOF and point to the new repository and site.
- The tool pages for [OpenEBS](../tools/openebs.md), [Prometheus](../tools/prometheus.md), [Grafana](../tools/grafana.md) and [Elasticsearch](../tools/elasticsearch.md) name SLOF where they describe what the project uses.
- The manual Locust install in [Locust](../tools/locust.md#deploy-with-helm) names its ConfigMap `slof-locustfile` and its load test `slof`.

These stay as they were, because they refer to GOXN itself:

- The GOXN comparisons in the change pages and in [Experiment design](../experiment-design.md).
- The link to the [GOXN replication package](https://github.com/JulianLegler/goxn-replication-package) in the README.
- The sidecar image `julianlegler/oxn-steering-container` in `oxn/orchestration/kubernetes_orchestrator.py`, which is published under that name.

**Why.** The repository is the code base of the SLOF thesis, not of GOXN. Links to `julianlegler.github.io/goxn` sent readers to the documentation of the baseline, which no longer matches this code.

**What this breaks.** A manual Locust install from the old page used the ConfigMap `goxn-locustfile`. Delete it with `kubectl delete configmap goxn-locustfile --namespace system-under-evaluation`.

## Known limitations

- The Python package, the `oxn` command and the `oxn-*` namespaces keep the OXN name. Renaming them would break every spec and cluster that uses them.
- The `author` in `setup.cfg` and `docs/conf.py` still lists the GOXN authors only.
