"""Source-only regression; receipts stay in the new experiment namespace."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

from scripts.prepare_active_evolution import audit_baseline
from skillforge.evolution_registry import immutable_json


def main():
    source=Path(__file__).resolve().parents[1]
    root=source/".runtime"/("active-source-check-"+uuid.uuid4().hex)
    root.mkdir(parents=True)
    for name in ("skillforge","tests","scripts","configs"):
        shutil.copytree(source/name,root/name,ignore=shutil.ignore_patterns("__pycache__","*.pyc","model.local.json","deployment.local.json"))
    shutil.copy2(source/"pyproject.toml",root/"pyproject.toml")
    env={k:v for k,v in os.environ.items() if not k.startswith("SKILLFORGE_")}
    env.update(PYTHONPATH=str(root),PYTHONUTF8="1",PYTHONIOENCODING="utf-8")
    result=subprocess.run([sys.executable,"-m","pytest","-q"],cwd=root,env=env,capture_output=True,text=True,encoding="utf-8")
    output=source/"results/active-evolution/v1/development"/root.name
    output.mkdir(parents=True)
    (output/"pytest.log").write_text(result.stdout+result.stderr,encoding="utf-8")
    audit=audit_baseline(source/"results/active-evolution/v1/preparation")
    report={"passed":result.returncode==0,"returncode":result.returncode,"historical_files":audit,
        "source_only_copy":str(root),"excluded":["data","results",".runtime","local_model_config","local_deployment_config"]}
    immutable_json(output/"report.json",report)
    print(result.stdout)
    print(json.dumps({"report":str(output/"report.json"),**report}))
    raise SystemExit(result.returncode)


if __name__=="__main__":
    main()
