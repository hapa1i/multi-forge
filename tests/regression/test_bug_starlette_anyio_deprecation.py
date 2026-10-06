"""The supported HTTP test client must import and run without deprecated APIs."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest

pytestmark = pytest.mark.regression


def test_testclient_lifespan_and_request_without_deprecation(tmp_path: Path) -> None:
    # Collection may already have imported TestClient, so use a fresh interpreter
    # to catch its import-time AnyIO alias access as well as request-time warnings.
    result = subprocess.run(
        [
            sys.executable,
            "-W",
            "error::DeprecationWarning",
            "-c",
            dedent("""
                from contextlib import asynccontextmanager

                from fastapi import FastAPI
                from fastapi.testclient import TestClient

                @asynccontextmanager
                async def lifespan(app):
                    app.state.started = True
                    yield
                    app.state.started = False

                app = FastAPI(lifespan=lifespan)

                @app.get("/health")
                async def health():
                    return {"started": app.state.started}

                with TestClient(app) as client:
                    response = client.get("/health")
                    assert response.status_code == 200
                    assert response.json() == {"started": True}
                assert app.state.started is False
                """),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
