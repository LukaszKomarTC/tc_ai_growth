# Canonical pre-push gate. Mirrors .github/workflows/ci.yml so failures are caught locally.
#
#   make check   -> editable build + import + pytest (in a throwaway venv) + PHP lint
#
# The editable build is the important part: `pip install -e .` exercises the setuptools build
# backend, which is what caught the flat-layout packaging error CI hit (and a deps-only local
# install would miss).

.PHONY: check test lint-php smoke clean

check: test lint-php
	@echo "== check OK =="

test:
	@echo "== editable build + import + pytest (mirrors CI) =="
	cd orchestrator && \
	  python3 -m venv .venv-check && \
	  . .venv-check/bin/activate && \
	  pip install -q --upgrade pip && \
	  pip install -e ".[dev]" && \
	  python -c "import tc_growth; print('import tc_growth: ok')" && \
	  python -m pytest -q && \
	  deactivate && rm -rf .venv-check

lint-php:
	@echo "== PHP lint (tc-growth-connector) =="
	@if command -v php >/dev/null 2>&1; then \
	  find wordpress-plugin/tc-growth-connector -name '*.php' -print0 | xargs -0 -n1 php -l ; \
	else \
	  echo "php not installed locally — skipped (CI runs it)"; \
	fi

smoke:
	@echo "== read-only smoke (staging) — invokes read tools only, never writes =="
	cd orchestrator && bash scripts/smoke.sh

clean:
	rm -rf orchestrator/.venv-check orchestrator/*.egg-info
