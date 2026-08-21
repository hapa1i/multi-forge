.PHONY: help deps test-unit test-integration test-regression test pre-commit pre-commit-md clean clean-docker clean-all

# uv includes the dev dependency group by default.
deps:
	@uv sync --quiet

help:
	@echo "Multi Forge - Available Make targets:"
	@echo ""
	@echo "  make test-unit          - Run unit tests (fast, no Docker required)"
	@echo "  make test-integration   - Run integration tests (requires Docker)"
	@echo "  make test-regression    - Run regression tests (fast, no Docker required)"
	@echo "  make test               - Run both unit and integration tests"
	@echo ""
	@echo "  make pre-commit         - Run all pre-commit hooks (ruff, black, isort, mypy, pyright, mdformat, gitleaks)"
	@echo "  make pre-commit-md      - Run pre-commit hooks on Markdown files only"
	@echo ""
	@echo "  make clean              - Remove caches and build artifacts"
	@echo "  make clean-docker       - Remove forge Docker test images"
	@echo "  make clean-all          - Remove caches + Docker images"
	@echo ""

test-unit: deps
	@echo "Running unit tests (excluding integration)..."
	uv run pytest tests/src -m "not integration" -v

test-integration: deps
	@echo "Running integration tests (requires Docker)..."
	./scripts/test-integration.sh

test-regression: deps
	@echo "Running regression tests..."
	uv run pytest tests/regression -m regression -v

test: test-unit test-integration
	@echo "All tests complete!"

pre-commit: deps
	@echo "Running pre-commit hooks..."
	uv run pre-commit run --all-files

pre-commit-md: deps
	@echo "Running pre-commit hooks for all not-ignored md files..."
	uv run pre-commit run --files $$(git ls-files -- '*.md') $$(git ls-files --others --exclude-standard -- '*.md')

clean:
	@echo "Cleaning caches and build artifacts..."
	rm -rf .pytest_cache
	rm -rf .mypy_cache
	rm -rf .ruff_cache
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	@echo "Clean complete!"

# Removing these images forces the next test run to rebuild them.
clean-docker:
	@echo "Removing forge Docker test images..."
	@docker images --format '{{.Repository}}:{{.Tag}}' | grep '^forge-claude-test:' | while read img; do \
		echo "  Removing $$img"; \
		docker rmi "$$img" 2>/dev/null || true; \
	done
	@echo "Docker clean complete!"

clean-all: clean clean-docker
