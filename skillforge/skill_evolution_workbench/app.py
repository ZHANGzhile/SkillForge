"""Independent local preview; no model, queue, lifespan or mutation routes."""
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse

from .data import SkillEvolutionView
from .stage2 import stage2_status
from .formal import formal_status, formal_artifact, formal_trace


app = FastAPI(title="SkillForge Two-Phase Evolution evidence", docs_url=None, redoc_url=None)
view = SkillEvolutionView()


@app.get("/")
def home(): return RedirectResponse("/skill-evolution")


@app.get("/skill-evolution")
def page(): return FileResponse(Path(__file__).with_name("page.html"), media_type="text/html")


@app.get("/api/skill-evolution/index")
def index():
    try: return view.index()
    except (ValueError, KeyError, OSError) as exc: raise HTTPException(409, "Saved evidence is inconsistent: "+str(exc)) from exc


@app.get("/api/skill-evolution/artifact")
def artifact(name: str):
    try: return FileResponse(view.artifact(name), media_type="application/json")
    except KeyError as exc: raise HTTPException(404, str(exc)) from exc


@app.get("/api/skill-evolution/stage2")
def stage2():
    try: return stage2_status()
    except (ValueError, KeyError, OSError) as exc: raise HTTPException(409, "Saved Stage 2 evidence is inconsistent: " + str(exc)) from exc


@app.get("/api/skill-evolution/trace")
def trace(stage: Literal["learn", "test"], index: int, method: Literal["A", "B", "C"] = "C", round_number: int = 1):
    try: return view.trace(stage=stage, index=index, method=method, round_number=round_number)
    except KeyError as exc: raise HTTPException(404, str(exc)) from exc
    except (ValueError, OSError) as exc: raise HTTPException(409, "Saved trace is inconsistent: "+str(exc)) from exc


@app.get("/api/skill-evolution/formal-stage2")
def formal_stage2():
    try: return formal_status()
    except (ValueError, KeyError, OSError) as exc: raise HTTPException(409, "Saved formal evidence is inconsistent: " + str(exc)) from exc


@app.get("/api/skill-evolution/formal-stage2-artifact")
def formal_stage2_artifact(name: str):
    try: return FileResponse(formal_artifact(name), media_type="application/json")
    except KeyError as exc: raise HTTPException(404, str(exc)) from exc
    except (ValueError, OSError) as exc: raise HTTPException(409, "Saved formal artifact is inconsistent: " + str(exc)) from exc


@app.get("/api/skill-evolution/formal-stage2-trace")
def formal_stage2_trace(index: int):
    try: return formal_trace(index)
    except KeyError as exc: raise HTTPException(404, str(exc)) from exc
    except (ValueError, OSError) as exc: raise HTTPException(409, "Saved formal trace is inconsistent: " + str(exc)) from exc
