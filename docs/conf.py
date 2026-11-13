project = "GOXN"
author = "Joshua Bauer and Julian Legler"
copyright = f"%Y, {author}"

extensions = ["myst_parser", "sphinxcontrib.mermaid"]
exclude_patterns = ["_build", "README.md"]

# The guides link to sections by heading, such as #remove-it
myst_heading_anchors = 3
# Plain ```mermaid fences render as diagrams here and on GitHub
myst_fence_as_directive = ["mermaid"]

html_theme = "sphinx_rtd_theme"
html_title = "GOXN"
html_baseurl = "https://julianlegler.github.io/goxn/"
