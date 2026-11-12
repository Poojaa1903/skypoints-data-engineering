VENV ?= .venv
PY := $(VENV)/bin/python
AS_OF ?= 2024-01-15

.PHONY: setup test run clean

setup:
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install -r requirements.txt

test:
	$(PY) -m pytest -q

run:
	PYTHONPATH=src $(PY) -m skypoints.pipeline --input data/input --output outputs --as-of $(AS_OF)

clean:
	rm -rf outputs .pytest_cache
