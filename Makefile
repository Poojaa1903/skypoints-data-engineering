VENV ?= .venv
PY := $(VENV)/bin/python
AS_OF ?= 2024-01-15

include config/paths.env

.PHONY: setup test bronze run clean

setup:
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install -r requirements.txt

test:
	$(PY) -m pytest -q

bronze:
	PYTHONPATH=src $(PY) -m bronze.bronze --input $(SOURCE_DIR) --bronze $(BRONZE_DIR) --load-date $(AS_OF)

run: bronze
	PYTHONPATH=src $(PY) -m pipeline --bronze $(BRONZE_DIR) --output $(OUTPUT_DIR) --as-of $(AS_OF)

clean:
	rm -rf $(OUTPUT_DIR) $(BRONZE_DIR) $(SILVER_DIR) $(GOLD_DIR) .pytest_cache
