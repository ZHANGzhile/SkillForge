"""Add Evolution to the existing app without editing its frozen source or HTML."""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from ..api import app
from .data import EvolutionView


view = EvolutionView()
page = Path(__file__).with_name("page.html")
original_page = Path(__file__).resolve().parents[1] / "static/workbench.html"
app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) != "/"]


@app.get("/", response_class=HTMLResponse)
def workbench_with_evolution():
    html = original_page.read_text(encoding="utf-8")
    link = '<a id="evolutionLink" href="/evolution" style="padding:10px;text-decoration:none;font-weight:600">Evolution ↗</a>'
    return HTMLResponse(html.replace("</nav>", link + "</nav>", 1))


@app.get("/evolution", response_class=HTMLResponse)
def evolution_page():
    return FileResponse(page, media_type="text/html")


@app.get("/api/evolution/index")
def evolution_index():
    try:
        return JSONResponse(view.index(), headers={"Cache-Control": "no-store"})
    except (ValueError, KeyError) as exc:
        raise HTTPException(409, "Evolution evidence is inconsistent: " + str(exc)) from exc


@app.get("/api/evolution/trace")
def evolution_trace(run: str):
    try:
        return JSONResponse(view.trace(run), headers={"Cache-Control": "no-store"})
    except KeyError as exc:
        raise HTTPException(404, "Unknown completed evolution run") from exc
    except ValueError as exc:
        raise HTTPException(409, "Evolution evidence is inconsistent: " + str(exc)) from exc


@app.get("/api/evolution/artifact")
def evolution_artifact(run: str, name: str):
    try:
        path = view.artifact(run, name)
        return FileResponse(path, media_type="application/json", filename=path.name)
    except KeyError as exc:
        raise HTTPException(404, "Artifact unavailable") from exc


# A read-only preview can coexist with ongoing GPU experiments. It has no
# Workbench lifespan, task queue, or model client and exposes only these views.
preview = FastAPI(title="SkillForge Evolution evidence preview")
preview.router.routes.extend(r for r in app.router.routes
                             if getattr(r, "path", "").startswith(("/evolution", "/api/evolution")))
