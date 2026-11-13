project = "SLOF"
author = "Joshua Bauer and Julian Legler"
copyright = f"%Y, {author}"

extensions = ["myst_parser", "sphinx_immaterial", "sphinx_immaterial.mermaid_diagrams"]
exclude_patterns = ["_build", "README.md"]

# The guides link to sections by heading, such as #remove-it
myst_heading_anchors = 3
# Plain ```mermaid fences render as diagrams here and on GitHub.
# setup() below maps them to the theme's own Mermaid directive.
myst_fence_as_directive = ["mermaid"]

html_theme = "sphinx_immaterial"
html_title = "SLOF"
html_baseurl = "https://tomijange.github.io/slof/"

html_theme_options = {
    "repo_url": "https://github.com/tomijange/slof",
    "repo_name": "tomijange/slof",
    "icon": {"repo": "fontawesome/brands/github"},
    "features": [
        "navigation.tracking",
        "navigation.tabs",
        "navigation.tabs.sticky",
        "navigation.sections",
        "navigation.top",
        "navigation.indexes",
        "search.highlight",
        "search.share",
        "content.code.copy",
        "toc.follow",
    ],
    "palette": [
        {
            "media": "(prefers-color-scheme)",
            "toggle": {"icon": "material/brightness-auto", "name": "Switch to light mode"},
        },
        {
            "media": "(prefers-color-scheme: light)",
            "scheme": "default",
            "primary": "indigo",
            "accent": "indigo",
            "toggle": {"icon": "material/brightness-7", "name": "Switch to dark mode"},
        },
        {
            "media": "(prefers-color-scheme: dark)",
            "scheme": "slate",
            "primary": "indigo",
            "accent": "indigo",
            "toggle": {"icon": "material/brightness-4", "name": "Switch to system preference"},
        },
    ],
}


def setup(app):
    from sphinx_immaterial.mermaid_diagrams import MermaidDirective

    app.add_directive("mermaid", MermaidDirective)
