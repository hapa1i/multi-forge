"""Search CLI commands for Forge transcript search.

Provides:
- forge search -q <query>: Search transcripts, output JSON
- forge search rebuild-index: Full index rebuild (writes three stores)
- forge search status: Show index statistics
- forge search clean: Remove orphaned documents

Query is passed via -q/--query option to avoid ambiguity with subcommand
names (Click groups parse positional args before subcommand resolution).

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
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.option("-q", "--query", type=str, default=None, help="Search query")
@click.option("--limit", "-n", type=int, default=10, help="Maximum results")
@click.option(
    "--scope",
    type=click.Choice(["project", "all"]),
    default="project",
    help="Search scope: current project (default) or all indexed projects",
)
@click.pass_context
def search_cmd(ctx: click.Context, query: str | None, limit: int, scope: str) -> None:
    """Search session transcripts.

    \b
    Examples:
      forge search -q "timeout config"   Search for "timeout config"
      forge search rebuild-index         Rebuild the search index
      forge search status                Show index statistics
    """
    if ctx.invoked_subcommand is not None:
        return

    if query is None:
        click.echo(ctx.get_help())
        return

    _run_search(query, limit=limit, scope=scope)


def _run_search(query: str, *, limit: int, scope: str) -> None:
    """Execute a search and output JSON results."""
    if scope == "all":
        _run_search_all_projects(query, limit=limit)
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
        output = {
            "query": query,
            "total_results": 0,
            "results": [],
            "error": f"Search index corrupted or outdated: {e}",
            "hint": "Run 'forge search rebuild-index' to rebuild.",
        }
        click.echo(json.dumps(output, indent=2))
        return

    if results is None:
        hint = "No transcripts indexed for this project. Run 'forge search rebuild-index' or use --scope all."
        try:
            from forge.install.hooks import has_forge_hook

            if not has_forge_hook(project_root, "Stop"):
                hint += " If hooks are not installed, transcripts are not captured automatically."
        except Exception:
            pass
        output = {
            "query": query,
            "total_results": 0,
            "results": [],
            "hint": hint,
        }
        click.echo(json.dumps(output, indent=2))
        return

    _output_results(query, results)


def _run_search_all_projects(query: str, *, limit: int) -> None:
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
            output = {
                "query": query,
                "total_results": 0,
                "results": [],
            }
            click.echo(json.dumps(output, indent=2))
            return
        output = {
            "query": query,
            "total_results": 0,
            "results": [],
            "hint": "No indexed transcripts. Run 'forge search rebuild-index' first.",
        }
        click.echo(json.dumps(output, indent=2))
        return

    # Merge and sort by score descending
    all_results.sort(key=lambda r: r.score, reverse=True)
    _output_results(query, all_results[:limit])


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


def _output_results(query: str, results: list) -> None:
    """Format and output search results as JSON."""
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
def clean_cmd() -> None:
    """Remove orphaned documents whose transcript files no longer exist.

    Scans all three stores and index state, removing entries that point
    to transcript files that have been deleted or moved.
    """
    console = Console()

    from forge.search.index_state import IndexStateStore

    project_root = _resolve_forge_root()
    doc_store = SearchDocumentStore(forge_root=project_root)
    bm25_store = BM25IndexStore(forge_root=project_root)
    content_store = ContentStore(forge_root=project_root)
    index_store = IndexStateStore(forge_root=project_root)

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
def status_cmd() -> None:
    """Show search index statistics."""
    console = Console()

    from forge.search.index_state import IndexStateStore

    project_root = _resolve_forge_root()
    doc_store = SearchDocumentStore(forge_root=project_root)
    bm25_store = BM25IndexStore(forge_root=project_root)
    index_store = IndexStateStore(forge_root=project_root)
    index_dir = project_root / ".forge" / "search-index"

    if not doc_store.exists():
        console.print("Search index: [yellow]not built[/yellow]")
        console.print(f"Index location: [dim]{display_path(index_dir)}[/dim]")
        console.print("\n[dim]Tip: Run 'forge search rebuild-index' to build.[/dim]")
        return

    documents = doc_store.read()
    state = index_store.read()

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
