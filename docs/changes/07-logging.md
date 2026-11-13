# 7. Logging

**Compared to GOXN:** `oxn` logs through module loggers with a coloured console format, and every run reports its phases and how long they took.

## Summary

Experiments run for many minutes on a remote cluster, and the log is often the only record of what happened. GOXN printed every line in one uncoloured format, and three modules logged through the root logger. It also said little about how long each phase took. This change makes the log show progress at a glance.

| | GOXN | After this change |
|---|---|---|
| Loggers | `kubernetes_orchestrator.py`, `treatments.py` and `docker_orchestration.py` call `logging.info` and similar on the root logger | `logging.getLogger(__name__)` in every module |
| Console format | `[date time] host/LEVEL/logger: message`, no colour | `time logger message`, coloured by level when stderr is a terminal |
| Run progress | Start and end of each run | Run ID, duration of deployment, each treatment and the whole run, captured row counts, Locust summary |
| Locust `setup_logging` | Always called | Only in local runner mode |
| `--loglevel`, `--logfile` | Experiment command only | Every subcommand |

## Console format

**Now documented in:** [Experiments: running an experiment](../experiments.md#running-an-experiment)

`oxn/common/log.py` adds a `konsole`-based `ConsoleFormatter` for the console. It shows the time and the logger name before each message and also colours info messages, which `konsole` leaves plain by default. It uses colour only when stderr is a terminal, so redirected output has no escape codes. `--logfile` keeps GOXN's format. `konsole` is a new dependency.

Modules that logged through the root logger now use their own logger, so every line names the module it came from.

## More messages

Every run now logs:

- Its run ID.
- How long deployment took until the SUE was ready.
- Each treatment as it is injected and cleaned, and how long it took.
- How many rows each response captured.
- A summary of Locust requests and failures.
- How long the whole run took.

## Locust and subcommands

- **Locust logging.** Locust's `setup_logging` replaces the root logger's handlers. It now only runs in local runner mode. When Locust runs in the cluster, calling it would turn off `oxn`'s own console formatting.
- **Subcommand defaults.** `--loglevel` and `--logfile` work on `oxn setup`, `oxn deploy` and `oxn teardown` too. `oxn setup` defaults to `warning`, so its interactive output stays readable.

**Why.** On a long run, you need to see which phase `oxn` is in and spot the one that takes too long, without reading every line.

## Tests

`test_log.py` covers the colours, the plain output without a terminal, and the time and origin of messages.

## Known limitations

Nothing is left open by this change.
