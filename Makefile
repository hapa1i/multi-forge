# Makefile for Multi-Forge
# Provides standard targets for testing, linting, and development

.PHONY: help deps test-unit test-integration test-regression test pre-commit pre-commit-md clean clean-docker clean-all

# Ensure dev dependencies are installed (fast no-op when already synced)
# Dev deps live in [dependency-groups] dev, which uv includes by default.
deps:
	@uv sync --quiet

# Default target: show help
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

# Run unit tests (excludes integration tests marked with @pytest.mark.integration)
test-unit: deps
	@echo "Running unit tests (excluding integration)..."
	uv run pytest tests/src -m "not integration" -v

# Run integration tests (requires Docker)
test-integration: deps
	@echo "Running integration tests (requires Docker)..."
	./scripts/test-integration.sh

# Run regression tests (bug-fix validation)
test-regression: deps
	@echo "Running regression tests..."
	uv run pytest tests/regression -m regression -v

# Run all tests (unit + integration)
test: test-unit test-integration
	@echo "All tests complete!"

# Run all pre-commit hooks
pre-commit: deps
	@echo "Running pre-commit hooks..."
	uv run pre-commit run --all-files

pre-commit-md: deps
	@echo "Running pre-commit hooks for all not-ignored md files..."
	uv run pre-commit run --files $$(git ls-files -- '*.md') $$(git ls-files --others --exclude-standard -- '*.md')

# Clean caches and build artifacts
clean:
	@echo "Cleaning caches and build artifacts..."
	rm -rf .pytest_cache
	rm -rf .mypy_cache
	rm -rf .ruff_cache
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	@echo "Clean complete!"

# Remove forge Docker test images (forces rebuild on next test run)
clean-docker:
	@echo "Removing forge Docker test images..."
	@docker images --format '{{.Repository}}:{{.Tag}}' | grep '^forge-claude-test:' | while read img; do \
		echo "  Removing $$img"; \
		docker rmi "$$img" 2>/dev/null || true; \
	done
	@echo "Docker clean complete!"

# Full clean: caches + Docker images
clean-all: clean clean-docker
