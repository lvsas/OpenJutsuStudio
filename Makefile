# One entry point for the whole project: make install, make run, make test.
PY  := .venv/bin/python
UV  := uv

.PHONY: install setup deps run check test audit help

help:
	@printf '%s\n' \
	  'install   install the environment and the local SDK proxy' \
	  'setup     app environment, node packs and models in one go (COMFYUI=/path)' \
	  'deps      only the node packs and weights (COMFYUI=/path)' \
	  'check     report what the executor is still missing (nodes, weights)' \
	  'run       start the proxy and the studio on 127.0.0.1:8000' \
	  'test      run the full test suite' \
	  'audit     verify every workflow graph is reachable and has a terminal'

install:
	bash scripts/setup.sh --with-proxy

setup:
	@test -n "$(COMFYUI)" || (printf 'Usage: make setup COMFYUI=/path/to/ComfyUI\n' && exit 1)
	bash scripts/setup.sh --with-proxy
	$(PY) scripts/install_executor.py --comfyui "$(COMFYUI)" --install
	$(PY) scripts/download_models.py --comfyui "$(COMFYUI)" --download

deps:
	@test -n "$(COMFYUI)" || (printf 'Usage: make deps COMFYUI=/path/to/ComfyUI\n' && exit 1)
	$(PY) scripts/install_executor.py --comfyui "$(COMFYUI)" --install
	$(PY) scripts/download_models.py --comfyui "$(COMFYUI)" --download

check:
	$(PY) scripts/check_dependencies.py --host $${COMFYUI_URL:-http://127.0.0.1:8188} --engine all

run:
	bash scripts/start_local.sh

test:
	$(PY) -m unittest discover -s tests -q

audit:
	$(PY) scripts/audit_workflow_graphs.py
