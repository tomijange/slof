# 10. Documentation site

**Compared to GOXN:** the documentation is a Sphinx site with guides and one page per tool, published with GitHub Pages, instead of one long README.

## Summary

GOXN documented installation, the Helm commands for every tool and the experiment workflow in its README. Much of it described `run_experiment_suite.sh` and versions that the earlier changes replaced. This change moves the documentation to `docs/`, rewrites it for the current workflow, and shortens the README to a quick start.

| | GOXN | After this change |
|---|---|---|
| Format | `README.md` | Sphinx site in `docs/`, MyST Markdown, Read the Docs theme |
| Structure | One page | Four guides and ten tool pages |
| Build | None | `make docs`, warnings are errors |
| Publishing | GitHub README | GitHub Pages, from `main` |
| README | Installation and every Helm command | Quick start and links into the site |

## Pages

**Now documented in:** [Overview](../index.md)

| Page | Covers |
|---|---|
| [Getting started](../getting-started.md) | Installing `oxn`, preparing a cluster, running a first experiment, running the tests |
| [Deployments](../deployments.md) | The `deployment` section, deploying and tearing down, reaching the cluster |
| [Experiments](../experiments.md) | Specs, treatments, the `oxn` command, results |
| [Architecture](../architecture.md) | The packages and how they work together during a run |
| Tool pages | OpenEBS, Prometheus, Grafana, Kepler, OpenTelemetry Demo, OpenTelemetry Collector, Jaeger, Elasticsearch, Istio and Locust: Helm command, values, how to check and remove each |

`docs/README.md` is the start page. Headings up to level 3 get anchors (`myst_heading_anchors = 3`), so pages link to sections.

**Why.** The README had grown into installation guide, tool reference and workflow description at once, and it no longer matched the code. Separate pages can be kept current one at a time, and the tool pages give each tool a single place for its version and values.

## Build and publishing

**Now documented in:** [Overview](../index.md)

- `make docs` runs `sphinx -M html docs docs/_build -W --keep-going`. `docs/requirements.txt` lists what the build needs.
- `.github/workflows/docs.yml` builds the site on pull requests that touch `docs/`, the workflow or the Makefile, and publishes it to GitHub Pages on pushes to `main`.

## Known limitations

Nothing is left open by this change.
