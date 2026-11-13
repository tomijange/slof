# Changes

This fork builds on [GOXN](https://github.com/JulianLegler/goxn) by Julian Legler. This section lists every change since then, one page per change, and compares each one to GOXN. Read them in order: later pages build on earlier ones.

## In order

| # | Change | Compared to GOXN |
|---|---|---|
| 1 | [Package layout](01-package-layout.md) | Modules in packages by responsibility, absolute imports, entry point `oxn.cli.main:main` |
| 2 | [Typed experiment specs](02-typed-specs.md) | A pydantic spec model instead of `schema` and nested dicts. Unknown keys stop the run |

## GOXN and now

What differs from GOXN today, by area. "Changed in" points to the change pages, "Documented in" to the pages that describe the current state.

| Area | GOXN | Now | Changed in | Documented in |
|---|---|---|---|---|
| Code layout | About 25 modules side by side in `oxn/` | Packages by responsibility | [1](01-package-layout.md#packages) | [Architecture](../architecture.md#packages) |
| Spec format | `schema` validation, unknown keys ignored | Typed pydantic model, unknown keys rejected | [2](02-typed-specs.md#the-spec-model) | [Experiments](../experiments.md#spec-structure) |

## Open limitations

What the changes so far leave open:

| Limitation | From |
|---|---|
| Several unit tests from GOXN fail or do not import. | [1](01-package-layout.md#known-limitations) |

## Writing a change page

Add a page to this folder with every change to the code, the specs, the deployments or the tooling:

- **Name.** Number it after the last page, for example `11-short-name.md`, and title it `# 11. Short name`.
- **Lists.** Add it at the bottom of the [In order](#in-order) table and of the toctree below. Update the [GOXN and now](#goxn-and-now) table if the change touches one of its areas, or add a row. Update [Open limitations](#open-limitations).
- **Perspective.** Compare to GOXN, not to the previous change, so each page reads on its own. Commit hashes and dates are not needed, the order is the number.

Each page uses the same structure:

1. **Compared to GOXN.** One line under the title that says what is different from GOXN after the change.
2. **Summary.** What the change does in a few sentences, and a table with GOXN and the state after the change.
3. **One section per part of the change.** A **Now documented in** line that links to the main docs, then what changed, **Why.** and, where users have to act, **What this breaks.**
4. **Known limitations.** What the change leaves open on purpose, with a status.

When a later change makes part of an older page wrong, leave the old text, add a short note that links to the newer page, and update the status of its known limitations.

```{toctree}
:hidden:

01-package-layout
02-typed-specs
```
