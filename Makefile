VENV ?= .venv
PY := $(VENV)/bin/python

include local/pipeline.env

.PHONY: setup test bronze run clean

setup:
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install -r requirements.txt

test:
	$(PY) -m pytest -q

# Restore gaps from MONITORING_DATE through yesterday.
bronze:
	PYTHONPATH=local:local/src $(PY) -m utils.backfill --land-only --input $(SOURCE_DIR) --bronze $(BRONZE_DIR) --silver $(SILVER_DIR) --gold $(GOLD_DIR)

run:
	PYTHONPATH=local:local/src $(PY) -m utils.backfill --input $(SOURCE_DIR) --bronze $(BRONZE_DIR) --silver $(SILVER_DIR) --gold $(GOLD_DIR)

clean:
	rm -rf $(OUTPUT_DIR) $(BRONZE_DIR) $(SILVER_DIR) $(GOLD_DIR) .pytest_cache
