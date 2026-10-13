"""Fail CI on LFS pointers or altered frozen SQLite bytes; never change data."""
import hashlib
import json
from pathlib import Path
import re
import subprocess


def main():
    root=Path(__file__).resolve().parents[1]
    fixture=root/'results/skill-evolution/v1.3/formal-P11-v1/agent/physical/9'
    databases=sorted(fixture.rglob('*.sqlite'))
    if not databases:raise ValueError('required frozen auditor fixture is missing')
    verified=[]
    for path in databases:
        data=path.read_bytes();relative=path.relative_to(root).as_posix()
        if data.startswith(b'version https://git-lfs.github.com/spec/v1'):
            raise ValueError('unhydrated Git LFS pointer: '+relative)
        if not data.startswith(b'SQLite format 3\0'):raise ValueError('not a SQLite database: '+relative)
        pointer=subprocess.check_output(['git','show','HEAD:'+relative],cwd=root).decode('utf-8')
        oid=re.search(r'^oid sha256:([0-9a-f]{64})$',pointer,re.M)
        size=re.search(r'^size ([0-9]+)$',pointer,re.M)
        digest=hashlib.sha256(data).hexdigest()
        if not oid or not size or digest!=oid[1] or len(data)!=int(size[1]):
            raise ValueError('Git LFS OID/size differs from frozen SQLite: '+relative)
        snapshot=path.parent/'snapshot.json'
        if snapshot.exists() and json.loads(snapshot.read_text(encoding='utf-8'))['body']['database_sha256']!=digest:
            raise ValueError('checkpoint SQLite digest differs: '+relative)
        verified.append({'path':relative,'bytes':len(data),'sha256':digest})
    print(json.dumps({'passed':True,'verified_databases':verified},indent=2))


if __name__=='__main__':main()
