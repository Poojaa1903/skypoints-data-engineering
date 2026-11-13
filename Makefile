VENV ?= .venv
PY := $(VENV)/bin/python
AS_OF ?= 2024-01-15

.PHONY: setup test bronze run clean

setup:
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install -r requirements.txt

test:
	$(PY) -m pytest -q

bronze:
	PYTHONPATH=src $(PY) -m skypoints.bronze --input data/input --bronze data/bronze --load-date $(AS_OF)

run: bronze
	PYTHONPATH=src $(PY) -m skypoints.pipeline --bronze data/bronze --output outputs --as-of $(AS_OF)

clean:
	rm -rf outputs data/bronze data/silver data/gold .pytest_cache
