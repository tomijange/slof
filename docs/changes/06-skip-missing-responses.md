# 6. Missing response data no longer aborts the run

**Compared to GOXN:** a response that captures no data is skipped with a warning, and the rest of the run is still stored and reported.

## Summary

In GOXN, one response without data crashed the run at the very end. By then the load phase and all treatments had already run, so every other response of that run was lost too. A typical cause is a metric name that changed with a chart version. This change skips such a response and keeps the rest.

| | GOXN | After this change |
|---|---|---|
| A response without data | `write_dataframe(None)` raises and the run aborts | Logged as a warning and skipped |
| Other responses of the run | Lost | Stored in `store.h5` and reported |
| HTTP errors after retries | A generic retry error | `raise_for_status()` with the real HTTP status |

## Skipping responses without data

**Now documented in:** [Experiments: results](../experiments.md#results)

When the observer cannot capture a response, it logs a warning, with the stack trace at debug level. The response then has no data, and two places skip it:

- `ExperimentRunner` does not label it with the treatment windows.
- The engine does not write it to `store.h5` and leaves it out of the report.

**Why.** A run takes many minutes of load and treatments. One bad query should cost one response, not the whole run.

## Retry policies

The Prometheus and Jaeger clients retry on 500, 502, 503 and 504. Their retry policies now set `raise_on_status=False`. Once the retries are used up, `raise_for_status()` raises with the real HTTP status and the warning above names it.

**Why.** Before, the error only said that the retries were exhausted, which hid whether the query was wrong or the server was down.

## Tests

`test_deployment.py` checks that responses without data are neither stored nor reported, and `test_observer.py` covers the observer.

## Known limitations

Nothing is left open by this change. Check the warnings after a run: a skipped response is missing from the results.
