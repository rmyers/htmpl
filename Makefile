# Common python Makefile rules, these must be included in
# the application Makefile and setup with the correct variables like:
#
#    # Important Paths
#    base_dir ?= $(shell git rev-parse --show-toplevel)
#    app_dir ?= $(shell git rev-parse --show-prefix)
#
#    # Service variables
#    docker_service_name := nucleus-test-service
#    docker_group := big-bend
#    service_name := nucleus_test_service-api
#    app_name := nucleus_test_service
#
#    # Conda-related paths
#    conda_env_dir ?= ./env
#    # Commands
#    CONDA_EXE ?= conda
#    conda_run := $(CONDA_EXE) run --live-stream --prefix $(conda_env_dir)
#
# Then include the help make file and python make file in order:
#
#    # Include the help command and make this the default rule.
#    include $(base_dir)/shared/help.mk
#    # Include python standard commands
#    include $(base_dir)/shared/python.mk
#

# Important Paths
base_dir ?= $(shell git rev-parse --show-toplevel)
app_dir ?= $(shell git rev-parse --show-prefix)
conda_env_dir ?= $(base_dir)/env

# Export environment variables
export PYTHONPATH = $(base_dir)/src

# Setup conda lock
CONDA_EXE ?= conda
CONDA_LOCK := $(CONDA_EXE) lock
CONDA_LOCK_FILE ?= conda-lock.yml
CONDA_LOCK_EXTRAS ?= "dev,all"
# Commands
conda_run := $(CONDA_EXE) run --live-stream --prefix $(conda_env_dir)


check-env:
	@if [ -z "$(CONDA_EXE)" ]; then \
		echo "Error: Please install 'conda' first"; \
		exit 1; \
	fi
	@if ! $(CONDA_LOCK) --help >/dev/null 2>&1; then \
		echo "Error: 'conda lock' command not available. Please install conda-lock plugin"; \
		exit 1; \
	fi

$(CONDA_LOCK_FILE): pyproject.toml
	$(CONDA_LOCK) --check-input-hash --file pyproject.toml --extras $(CONDA_LOCK_EXTRAS)

lock: check-env $(CONDA_LOCK_FILE)  ## Lock Conda dependencies in project

lock-force: check-env  ## Force lock Conda dependencies in project
	$(CONDA_LOCK) --file pyproject.toml --extras $(CONDA_LOCK_EXTRAS)

setup: check-env $(CONDA_LOCK_FILE)  ## Setup local environment
	$(CONDA_LOCK) install -E all --log-level ERROR -p $(conda_env_dir) $(CONDA_LOCK_FILE)

type-check:  ## Run mypy to check static types
	$(conda_run) mypy $(args)

test:  ## Run all the unit tests
	$(conda_run) pytest -vv $(ARGS) $(args) tests/

test-pdb:  ## Run all the unit tests, start the Python debugger on errros
	$(conda_run) pytest -vv $(ARGS) $(args) tests/ --log-cli-level=warning --pdb

test-integration:  ## Run the integration tests
	$(conda_run) pytest --no-cov -vv $(ARGS) $(args) tests/ --integration -m integration

test-all:  ## Run all the tests, including integration tests
	$(conda_run) pytest -vv $(ARGS) $(args) tests/ --integration

test-failed:  ## Run tests that failed or all if none failed
	$(conda_run) pytest -vv --lf --no-cov $(ARGS) $(args) tests/

test-only:  ## Run only the tests specified (make test-only args=tests/api/endpoints)
	$(conda_run) pytest -vv --no-cov $(ARGS) $(args)

install-hooks:  ## Install pre-commit hooks
	pre-commit install-hooks

pre-commit:  ## Run pre-commit on the repo
	pre-commit run --verbose --show-diff-on-failure --color=always --all-files

dev: ## Run example
	cd examples && $(conda_run) python app.py

dev-forms: ## Run example
	cd examples && $(conda_run) python forms.py

repl:  ## Get a python repl that is configured properly
	$(conda_run) python

clean:  ## Clean up cache and temporary files and stop containers
	find . -name \*.py[cod] -delete
	rm -rf .pytest_cache .mypy_cache .coverage coverage.xml htmlcov junit dist

build:  ## Run uv build
	rm -rf dist
	uv build

publist:  ## Run uv publish
	uv publish
