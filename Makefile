PY := $(wildcard .venv/Scripts/python.exe)
ifeq ($(PY),)
PY := .venv/bin/python
endif

test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check .

run:
	$(PY) -m uvicorn app.main:app --reload --port 8000
