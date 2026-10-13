"""Standalone read-only preview; no Workbench model lifespan or task queue."""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from .data import ExecutionView


app = FastAPI(title='Execution-Aware Evolution evidence')
view = ExecutionView()


@app.get('/')
@app.get('/execution-evolution')
def page():
    return FileResponse(Path(__file__).with_name('page.html'), media_type='text/html')


@app.get('/api/execution-evolution/index')
def index():
    try:
        return JSONResponse(view.index(), headers={'Cache-Control': 'no-store'})
    except (ValueError, KeyError, FileNotFoundError) as exc:
        raise HTTPException(409, 'Recorded evidence unavailable or inconsistent: '+str(exc)) from exc


@app.get('/api/execution-evolution/task')
def task(key: str):
    try:
        return JSONResponse(view.task(key), headers={'Cache-Control': 'no-store'})
    except KeyError as exc:
        raise HTTPException(404, 'Unknown recorded task') from exc
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(409, 'Recorded task is inconsistent') from exc
