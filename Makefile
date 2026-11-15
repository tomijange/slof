.PHONY: coverage lint format hooks build docs docs-serve clean setup-cluster deploy-sue teardown-sue

SPEC ?= experiments/test.yml

coverage:
	python -W ignore -m coverage run -m unittest discover -s oxn/tests/

# Checks without changing files, as in CI
lint:
	ruff check .
	ruff format --check .
	yamllint --strict .
	ty check

# Fixes what Ruff can fix automatically and formats the Python code.
# yamllint only checks, so YAML findings are fixed by hand.
format:
	ruff check --fix .
	ruff format .

# Runs make lint before every commit, with the hook in .githooks/
hooks:
	git config core.hooksPath .githooks

build:
	python -m build

docs:
	python -m sphinx -M html docs docs/_build -W --keep-going

DOCS_PORT ?= 8000

docs-serve:
	python -m sphinx_autobuild docs docs/_build/html --port $(DOCS_PORT) --open-browser

clean:
	rm -rf build/ && rm -rf dist/ && rm -rf oxn.egg-info/ && rm -rf docs/_build/
	

setup-cluster:
	oxn setup

deploy-sue:
	oxn deploy $(SPEC)

teardown-sue:
	oxn teardown $(SPEC)
