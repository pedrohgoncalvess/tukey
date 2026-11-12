UV ?= uv
PROJECT_PATH ?= .
ARGS ?=

ifeq ($(OS),Windows_NT)
SHELL := cmd.exe
.SHELLFLAGS := /c
endif

.DEFAULT_GOAL := help
.PHONY: setup install uninstall run test format check tokens help

setup:
	$(UV) sync --group dev

install:
	$(UV) tool install --reinstall --python 3.12 .
	$(UV) tool update-shell
	@echo Open a new terminal to use tukey.

uninstall:
	$(UV) tool uninstall tukey-code

run:
	$(UV) run tukey "$(PROJECT_PATH)" $(ARGS)

test:
	$(UV) run pytest

format:
	$(UV) run black src tests

check:
	$(UV) run black --check src tests
	$(UV) run pytest

tokens:
	$(UV) run python -m tukey.design > docs/design-tokens.css

help:
	@echo make setup   - install development dependencies
	@echo make install - install tukey in an isolated user environment and configure PATH
	@echo make run PROJECT_PATH=path ARGS="--output report.json"
	@echo make test / make check / make format
	@echo make tokens - export shared design tokens as CSS
	@echo make uninstall - remove the installed command
