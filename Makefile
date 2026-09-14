.PHONY: trace-check contract-check

trace-check:
	python scripts/check_traceability.py
	python scripts/check_links.py

contract-check:
	python scripts/check_contracts.py
	cd frontend && npm run contract:check