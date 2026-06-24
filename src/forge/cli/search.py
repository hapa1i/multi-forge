"""Search CLI commands for Forge transcript search.

Provides:
- forge search query <terms>: Search transcripts (human table; --json for the machine-readable shape)
- forge search rebuild-index: Full index rebuild (writes three stores)
- forge search status: Show index statistics
- forge search clean: Preview orphaned documents (--yes to prune)

Stores are per-project at <forge_root>/.forge/search-index/:
- documents.json (v2): metadata only
- bm25_index.json: precomputed BM25 data structures
- content.json: document content for snippet extraction
"""

from __future__ import annotations

import json
from pathlib import Path

import click
from rich.console import Console

from forge.cli.output import print_error_with_tip, print_tip
from forge.core.paths import display_path
from forge.core.state import SchemaVersionError
from forge.search.bm25_store import BM25IndexData, BM25IndexStore
from forge.search.content_store import ContentStore
from forge.search.engine import search_from_index
from forge.search.exceptions import (
    BM25IndexCorruptedError,
    ContentStoreCorruptedError,
    SearchDocumentStoreCorruptedError,
)
from forge.search.store import SearchDocumentStore


def _resolve_forge_root() -> Path:
    """Resolve the current Forge project root, falling back to cwd."""
    from forge.session.artifacts import resolve_forge_root

    try:
        return resolve_forge_root(Path.cwd())
    except Exception:
        return Path.cwd().resolve()


@click.group(
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
def search_cmd() -> None:
    """Search session transcripts.

    \b
    Examples:
      forge search query "timeout config"  Search for "timeout config"
      forge search rebuild-index           Rebuild the search index
      forge search status                  Show index statistics
    """


@search_cmd.command("query")
@click.argument("terms", nargs=-1, required=True)
@click.option("--limit", "-n", type=int, default=10, help="Maximum results")
@click.option(
    "--scope",
    type=click.Choice(["project", "all"]),
    default="project",
    help="Search scope: current project (default) or all indexed projects",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def query_cmd(terms: tuple[str, ...], limit: int, scope: str, as_json: bool) -> None:
    """Search indexed session transcripts.

    Prints a result table by default; pass --json for the machine-readable shape
    (stable scripting contract: query / total_results / results[]).
    """
    query = " ".join(terms)

    _run_search(query, limit=limit, scope=scope, as_json=as_json)


def _run_search(query: str, *, limit: int, scope: str, as_json: bool) -> None:
    """Execute a project-scoped search; render a table, or the stable JSON with --json."""
    if scope == "all":
        _run_search_all_projects(query, limit=limit, as_json=as_json)
        return

    project_root = _resolve_forge_root()

    try:
        results = _search_project(project_root, query, limit=limit)
    except (
        SearchDocumentStoreCorruptedError,
        BM25IndexCorruptedError,
        ContentStoreCorruptedError,
        SchemaVersionError,
    ) as e:
        if as_json:
            output = {
                "query": query,
                "total_results": 0,
                "results": [],
                "error": f"Search index corrupted or outdated: {e}",
                "hint": "Run 'forge search rebuild-index' to rebuild.",
            }
            click.echo(json.dumps(output, indent=2))
            return
        print_error_with_tip(
            f"Search index corrupted or outdated: {e}",
            "Run 'forge search rebuild-index' to rebuild.",
            console=Console(),
        )
        return

    if results is None:
        hint = "No transcripts indexed for this project. Run 'forge search rebuild-index' or use --scope all."
        try:
            from forge.install.hooks import has_forge_hook

            if not has_forge_hook(project_root, "Stop"):
                hint += " If hooks are not installed, transcripts are not captured automatically."
        except Exception:
            pass
        if as_json:
            output = {
                "query": query,
                "total_results": 0,
                "results": [],
                "hint": hint,
            }
            click.echo(json.dumps(output, indent=2))
            return
        print_tip(hint, console=Console())
        return

    _output_results(query, results, as_json=as_json)


def _run_search_all_projects(query: str, *, limit: int, as_json: bool) -> None:
    """Search across all known project indices."""
    import logging

    from forge.session.index import IndexStore

    logger = logging.getLogger(__name__)
    current_root = _resolve_forge_root()
    project_roots = {str(current_root)}

    try:
        index = IndexStore()
        sessions = index.list_sessions()
        project_roots.update((entry.forge_root or entry.worktree_path) for _, entry in sessions)
    except Exception:
        pass

    all_results: list = []
    searched_any_index = False
    for root in project_roots:
        try:
            results = _search_project(Path(root), query, limit=limit)
            if results is not None:
                searched_any_index = True
                all_results.extend(results)
        except (
            SearchDocumentStoreCorruptedError,
            BM25IndexCorruptedError,
            ContentStoreCorruptedError,
            SchemaVersionError,
        ) as e:
            logger.warning("Skipping corrupted search index in %s: %s", root, e)
            continue
        except Exception as e:
            logger.debug("Skipping project %s: %s", root, e)
            continue

    if not all_results:
        if searched_any_index:
            if as_json:
                output = {
                    "query": query,
                    "total_results": 0,
                    "results": [],
                }
                click.echo(json.dumps(output, indent=2))
                return
            _output_results(query, [], as_json=False)
            return
        if as_json:
            output = {
                "query": query,
                "total_results": 0,
                "results": [],
                "hint": "No indexed transcripts. Run 'forge search rebuild-index' first.",
            }
            click.echo(json.dumps(output, indent=2))
            return
        print_tip("No indexed transcripts. Run 'forge search rebuild-index' first.", console=Console())
        return

    # Merge and sort by score descending
    all_results.sort(key=lambda r: r.score, reverse=True)
    _output_results(query, all_results[:limit], as_json=as_json)


def _search_project(project_root: Path, query: str, *, limit: int):
    """Search a single project using its persistent BM25 index.

    Returns list of SearchResult, or None if no index exists.
    Raises on corruption (caller handles).
    """
    bm25_store = BM25IndexStore(forge_root=project_root)
    bm25_index = bm25_store.read()
    if bm25_index is None:
        return None

    doc_store = SearchDocumentStore(forge_root=project_root)
    doc_metas = doc_store.read()
    if not doc_metas and not bm25_index.doc_keys:
        return None

    meta_map = {m.transcript_path: m for m in doc_metas}

    content_store = ContentStore(forge_root=project_root)

    return search_from_index(
        query,
        doc_keys=bm25_index.doc_keys,
        term_freqs=bm25_index.term_freqs,
        doc_freqs=bm25_index.doc_freqs,
        doc_lens=bm25_index.doc_lens,
        avgdl=bm25_index.avgdl,
        k1=bm25_index.k1,
        b=bm25_index.b,
        content_loader=content_store.read_keys,
        doc_metadata=meta_map,
        limit=limit,
    )


def _output_results(query: str, results: list, *, as_json: bool) -> None:
    """Render search results: a Rich table by default, or the stable JSON shape with --json."""
    if as_json:
        output = {
            "query": query,
            "total_results": len(results),
            "results": [
                {
                    "session_name": r.session_name,
                    "session_id": r.session_id,
                    "score": r.score,
                    "snippet": r.snippet,
                    "transcript_path": r.transcript_path,
                    "metadata": r.metadata,
                }
                for r in results
            ],
        }
        click.echo(json.dumps(output, indent=2))
        return

    console = Console()
    if not results:
        console.print(f"[dim]No results for '{query}'.[/dim]")
        return

    from rich.table import Table

    table = Table(show_header=True, header_style="bold")
    table.add_column("Score", justify="right", style="cyan")
    table.add_column("Session")
    table.add_column("Snippet", style="dim", overflow="fold")
    for r in results:
        table.add_row(f"{r.score:.2f}", r.session_name, r.snippet)
    console.print(table)
    console.print(f"Found {len(results)} result(s).")


@search_cmd.command("rebuild-index")
def rebuild_index_cmd() -> None:
    """Rebuild search index from all transcript artifacts.

    Scans .forge/artifacts/**/transcripts/*.jsonl in the current project,
    extracts content, and writes to all three per-project stores
    (documents.json, bm25_index.json, content.json).
    This is a full reset — all data for this project is replaced.
    """
    console = Console()

    from forge.search.engine import BM25
    from forge.search.extractor import decompose_document, extract_document
    from forge.search.index_state import IndexStateStore

    project_root = _resolve_forge_root()
    artifacts_dir = project_root / ".forge" / "artifacts"

    if not artifacts_dir.is_dir():
        console.print("[dim]No artifacts directory found.[/dim]")
        return

    doc_store = SearchDocumentStore(forge_root=project_root)
    bm25_store = BM25IndexStore(forge_root=project_root)
    content_store = ContentStore(forge_root=project_root)
    index_store = IndexStateStore(forge_root=project_root)

    project_root_str = str(project_root)

    # Extract all docs
    new_docs = []
    errors = 0

    for session_dir in sorted(artifacts_dir.iterdir()):
        if not session_dir.is_dir():
            continue
        session_name = session_dir.name
        transcripts_dir = session_dir / "transcripts"
        if not transcripts_dir.is_dir():
            continue

        for jsonl_file in sorted(transcripts_dir.glob("*.jsonl")):
            session_id = jsonl_file.stem
            try:
                doc = extract_document(
                    transcript_path=jsonl_file,
                    session_name=session_name,
                    session_id=session_id,
                    worktree_path=project_root_str,
                )
                new_docs.append(doc)
            except Exception as e:
                console.print(f"[yellow]Warning:[/yellow] Failed to extract {jsonl_file.name}: {e}")
                errors += 1

    # Decompose into three-store components
    metas = []
    content_map = {}
    all_tokens = []

    for doc in new_docs:
        meta, _, _, content = decompose_document(doc)
        metas.append(meta)
        content_map[doc.transcript_path] = content
        all_tokens.append(doc.tokens if doc.tokens is not None else [])

    # Build BM25 from all tokens at once (efficient bulk construction)
    bm25 = BM25(all_tokens)
    precomputed = bm25.to_precomputed()

    bm25_data = BM25IndexData(
        doc_keys=[doc.transcript_path for doc in new_docs],
        doc_lens=precomputed["doc_lens"],
        term_freqs=precomputed["term_freqs"],
        doc_freqs=precomputed["doc_freqs"],
        avgdl=precomputed["avgdl"],
        k1=precomputed["k1"],
        b=precomputed["b"],
    )

    # Replace all three stores under locks
    doc_store.replace_all(metas)
    bm25_store.replace_all(bm25_data)
    content_store.replace_all(content_map)

    # Mark all as indexed
    for doc in new_docs:
        try:
            index_store.mark_indexed(Path(doc.transcript_path))
        except (FileNotFoundError, ValueError):
            pass

    # Prune stale entries from index state (stores were fully replaced)
    index_store.prune_missing()

    console.print(f"[green]Indexed {len(new_docs)} transcripts.[/green]")
    if errors:
        console.print(f"[yellow]{errors} files failed extraction.[/yellow]")


@search_cmd.command("clean")
@click.option("--yes", "-y", is_flag=True, help="Actually prune (default is a preview)")
def clean_cmd(yes: bool) -> None:
    """Remove orphaned documents whose transcript files no longer exist.

    Scans all three stores and index state for entries that point to transcript
    files that have been deleted or moved. Previews by default; pass --yes to
    actually prune.
    """
    console = Console()

    from forge.search.index_state import IndexStateStore

    project_root = _resolve_forge_root()
    doc_store = SearchDocumentStore(forge_root=project_root)
    bm25_store = BM25IndexStore(forge_root=project_root)
    content_store = ContentStore(forge_root=project_root)
    index_store = IndexStateStore(forge_root=project_root)

    if not yes:
        missing_docs = doc_store.find_missing()
        missing_index = index_store.find_missing()
        if missing_docs or missing_index:
            console.print(
                f"Would prune [cyan]{len(missing_docs)}[/cyan] orphaned document(s)"
                f" and [cyan]{len(missing_index)}[/cyan] stale index entr(ies)."
            )
            print_tip("Use --yes to prune.", console=console)
        else:
            console.print("[dim]No orphaned entries found.[/dim]")
        return

    removed_docs = doc_store.prune_missing()

    # Also remove from BM25 index and content store
    for path in removed_docs:
        bm25_store.remove_document(path)
        content_store.remove(path)

    removed_index = index_store.prune_missing()

    if removed_docs or removed_index:
        console.print(
            f"Pruned [cyan]{len(removed_docs)}[/cyan] orphaned documents"
            f" and [cyan]{len(removed_index)}[/cyan] stale index entries."
        )
    else:
        console.print("[dim]No orphaned entries found.[/dim]")


@search_cmd.command("status")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def status_cmd(as_json: bool) -> None:
    """Show search index statistics."""
    console = Console()

    from forge.search.index_state import IndexStateStore

    project_root = _resolve_forge_root()
    doc_store = SearchDocumentStore(forge_root=project_root)
    bm25_store = BM25IndexStore(forge_root=project_root)
    index_store = IndexStateStore(forge_root=project_root)
    index_dir = project_root / ".forge" / "search-index"

    if not doc_store.exists():
        if as_json:
            click.echo(
                json.dumps(
                    {
                        "built": False,
                        "index_location": str(index_dir),
                        "documents_indexed": 0,
                        "files_tracked": 0,
                        "updated_at": None,
                        "sessions": 0,
                        "bm25": None,
                    },
                    indent=2,
                )
            )
            return
        console.print("Search index: [yellow]not built[/yellow]")
        console.print(f"Index location: [dim]{display_path(index_dir)}[/dim]")
        print_tip("Run 'forge search rebuild-index' to build.", console=console)
        return

    documents = doc_store.read()
    state = index_store.read()

    if as_json:
        bm25_index = bm25_store.read()
        click.echo(
            json.dumps(
                {
                    "built": True,
                    "index_location": str(index_dir),
                    "documents_indexed": len(documents),
                    "files_tracked": len(state.indexed_files),
                    "updated_at": str(state.updated_at) if state.updated_at else None,
                    "sessions": len({d.session_name for d in documents}),
                    "bm25": (
                        {"documents": len(bm25_index.doc_keys), "unique_terms": len(bm25_index.doc_freqs)}
                        if bm25_index is not None
                        else None
                    ),
                },
                indent=2,
            )
        )
        return

    console.print(f"Index location: [dim]{display_path(index_dir)}[/dim]")
    console.print(f"Documents indexed: [cyan]{len(documents)}[/cyan]")
    console.print(f"Files tracked: [cyan]{len(state.indexed_files)}[/cyan]")
    if state.updated_at:
        console.print(f"Last updated: [dim]{state.updated_at}[/dim]")

    if documents:
        session_names = {d.session_name for d in documents}
        console.print(f"Sessions: [cyan]{len(session_names)}[/cyan]")

    # BM25 index stats
    bm25_index = bm25_store.read()
    if bm25_index is not None:
        console.print(
            f"BM25 index: [cyan]{len(bm25_index.doc_keys)}[/cyan] documents, "
            f"[cyan]{len(bm25_index.doc_freqs)}[/cyan] unique terms"
        )
