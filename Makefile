.PHONY: install fmt lint type test check run
install: ; uv sync
fmt:     ; uv run ruff format . && uv run ruff check --fix .
lint:    ; uv run ruff check . && uv run ruff format --check .
type:    ; uv run basedpyright
test:    ; uv run pytest
check: lint type test
run:     ; uv run discord-sound-bot
