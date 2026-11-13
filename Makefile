.PHONY: coverage build docs clean setup-cluster deploy-sue teardown-sue

SPEC ?= experiments/test.yml

coverage:
	python -W ignore -m coverage run -m unittest discover -s oxn/tests/

build:
	python -m build

docs:
	python -m sphinx -M html docs docs/_build -W --keep-going

clean:
	rm -rf build/ && rm -rf dist/ && rm -rf oxn.egg-info/ && rm -rf docs/_build/
	

setup-cluster:
	oxn setup

deploy-sue:
	oxn deploy $(SPEC)

teardown-sue:
	oxn teardown $(SPEC)
