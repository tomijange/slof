# 15. Material theme for the docs

**Compared to GOXN:** the documentation site uses the Material theme (`sphinx-immaterial`), with tabs, search, a light and dark mode and the theme's own Mermaid rendering. GOXN had no documentation site.

## Summary

[Change 10](10-documentation-site.md) built the site with the Read the Docs theme, and [change 11](11-current-stack-specs.md#documentation) added `sphinxcontrib-mermaid` for diagrams. This change replaces both with `sphinx-immaterial`, a Sphinx port of Material for MkDocs.

| Area | GOXN | After this change |
|---|---|---|
| Theme | No site, `README.md` | `sphinx-immaterial` 0.13.11, indigo, follows the system light or dark mode with a toggle |
| Navigation | One page | Tabs for Guides and Tools, a side bar per tab, a table of contents per page, back-to-top button |
| Search | GitHub page search | Search box in the header, highlights the hits on the page |
| Mermaid | None | The theme's own renderer, colours follow the light or dark mode |
| Repository link | None | `tomijange/slof` in the header |

## Theme

**Now documented in:** [Overview](../index.md)

`docs/conf.py` sets `html_theme = "sphinx_immaterial"` and configures it in `html_theme_options`:

- **Palette.** Indigo as primary and accent colour. Three states: system preference, light (`default`) and dark (`slate`). The icon next to the search box cycles through them.
- **Features.** `navigation.tabs` and `navigation.tabs.sticky` turn the two toctree captions, Guides and Tools, into tabs. `navigation.sections`, `navigation.indexes`, `navigation.tracking` and `navigation.top` arrange the side bar, keep the URL on the current section and add a back-to-top button. `search.highlight`, `search.share`, `content.code.copy` and `toc.follow` add search highlights, shareable search links, copy buttons on code blocks and a table of contents that follows the scroll position.
- **Repository.** `repo_url` and `repo_name` show `tomijange/slof` with its star and fork count in the header.

`docs/requirements.txt` lists `sphinx-immaterial==0.13.11` in place of `sphinx-rtd-theme`.

**Why.** The Read the Docs theme lists every page in one side bar and has no dark mode. With 14 change pages and ten tool pages the side bar grew long. Tabs split guides from tool pages, and the theme follows the reader's system colour scheme.

**What this breaks.** Run `pip install -r docs/requirements.txt` again before `make docs` or `make docs-serve`. URLs and anchors are unchanged.

## Mermaid diagrams

**Now documented in:** [Experiment design](../experiment-design.md#what-gets-measured)

The theme's script looks for `.mermaid` elements and loads its own copy of Mermaid for them. `sphinxcontrib-mermaid` also renders `.mermaid` elements, so with both, the theme failed to load its copy and the diagrams stayed as source text. This change removes `sphinxcontrib-mermaid` and loads `sphinx_immaterial.mermaid_diagrams` instead. That extension names its directive `md-mermaid`, so a `setup()` function in `docs/conf.py` registers it as `mermaid` too. Plain `mermaid` code fences still render on the site and on GitHub.

**Why.** One renderer for diagrams. The theme's renderer draws the diagrams in the theme's colours, so they match the light and dark mode. Mermaid no longer loads from a CDN, because the theme ships its own copy.

## Known limitations

Nothing is left open by this change.
