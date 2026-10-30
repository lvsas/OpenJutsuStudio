# One entry point for the whole project: make install, make run, make test.
PY  := .venv/bin/python
UV  := uv

.PHONY: install run check test audit clean-reels help

help:
	@printf '%s\n' \
	  'install   install the environment and the local SDK proxy' \
	  'check     report what the executor is missing (nodes, weights)' \
	  'run       start the proxy and the studio on 127.0.0.1:8000' \
	  'test      run the full test suite' \
	  'audit     verify every workflow graph is reachable and has a terminal'

install:
	bash scripts/setup.sh --with-proxy

check:
	$(PY) scripts/check_dependencies.py --host $${COMFYUI_URL:-http://127.0.0.1:8188} --engine all

run:
	bash scripts/start_local.sh

test:
	$(PY) -m unittest discover -s tests -q

audit:
	$(PY) scripts/audit_workflow_graphs.py
