.PHONY: all test audit install clean

PYTHON ?= python3

all: test

test:
	$(PYTHON) -m unittest discover tests/

audit:
	$(PYTHON) scripts/audit_package.py

install:
	$(PYTHON) -m pip install -e .

clean:
	rm -rf build/ dist/ *.egg-info .pytest_cache/
	find . -type d -name "__pycache__" -exec rm -rf {} +
