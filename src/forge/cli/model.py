"""Model catalog and backend CLI namespace."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from typing import Any

import click
from rich.console import Console
from rich.table import Table

from forge.cli.backend import backend
from forge.cli.output import err_console, print_error
from forge.core.models.catalog import ModelCatalogError, load_model_catalog
from forge.core.models.types import ModelCatalog, ModelSpec


@click.group(no_args_is_help=True, context_settings={"help_option_names": ["-h", "--help"]})
def model() -> None:
    """Inspect the model catalog and backends."""


def _model_record(model_id: str, spec: ModelSpec) -> dict[str, Any]:
    return asdict(spec) | {"model_id": model_id}


def _catalog_payload(catalog: ModelCatalog) -> dict[str, Any]:
    return {
        "schema_version": catalog.schema_version,
        "models": {model_id: asdict(spec) for model_id, spec in sorted(catalog.models.items())},
        "aliases": dict(sorted(catalog.aliases.items())),
        "defaults": {provider: dict(tiers) for provider, tiers in sorted(catalog.defaults.items())},
    }


def _capabilities(spec: ModelSpec) -> str:
    caps = []
    if spec.supports_thinking:
        caps.append("thinking")
    if spec.supports_images:
        caps.append("images")
    if spec.supports_verbosity:
        caps.append("verbosity")
    if spec.use_responses_api:
        caps.append("responses")
    if spec.supports_1m_context:
        caps.append("1m")
    return ", ".join(caps) if caps else "-"


def _print_catalog(catalog: ModelCatalog, console: Console) -> None:
    table = Table(title="Forge Model Catalog")
    table.add_column("MODEL", style="cyan")
    table.add_column("NAME")
    table.add_column("SCORE", justify="right")
    table.add_column("CONTEXT", justify="right")
    table.add_column("OUTPUT", justify="right")
    table.add_column("CAPABILITIES")

    for record in (_model_record(model_id, spec) for model_id, spec in sorted(catalog.models.items())):
        table.add_row(
            record["model_id"],
            record["friendly_name"],
            str(record["intelligence_score"]),
            str(record["context_window_tokens"]),
            str(record["max_output_tokens"]),
            _capabilities(catalog.models[record["model_id"]]),
        )

    console.print(table)

    defaults_table = Table(title="Provider Defaults")
    defaults_table.add_column("PROVIDER", style="cyan")
    defaults_table.add_column("HAIKU")
    defaults_table.add_column("SONNET")
    defaults_table.add_column("OPUS")

    for provider, tiers in sorted(catalog.defaults.items()):
        defaults_table.add_row(provider, tiers.get("haiku", "-"), tiers.get("sonnet", "-"), tiers.get("opus", "-"))

    console.print()
    console.print(defaults_table)
    console.print(f"\n[dim]{len(catalog.models)} models, {len(catalog.aliases)} aliases[/dim]")


@model.command("catalog")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def catalog_cmd(as_json: bool) -> None:
    """Show the static model capability catalog."""
    console = Console(width=200)
    try:
        catalog = load_model_catalog()
    except ModelCatalogError as e:
        # Diagnostics to stderr so `--json` stdout stays parseable (cli_style_guidelines.md "Output Streams").
        print_error(str(e), console=err_console)
        sys.exit(1)

    if as_json:
        click.echo(json.dumps(_catalog_payload(catalog), indent=2, default=str))
        return

    _print_catalog(catalog, console)


model.add_command(backend, name="backend")
