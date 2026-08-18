#!/usr/bin/env python3
"""Re-audit a relocatable bundle; the manifest is data, never authority."""
from __future__ import annotations
import argparse, hashlib, json, os, pathlib, subprocess, sys
import re
PRIVATE=('libggml','libllama','libmtmd','libomni')
def ldd_failures(output, root):
 allowed=(root/'lib').resolve(); errors=[]
 for line in output.splitlines():
  if 'not found' in line: errors.append('not found'); continue
  m=re.search(r'=>\s+(\S+)',line)
  if not m: continue
  candidate=pathlib.Path(m.group(1)).resolve(strict=False)
  if any(name in line for name in PRIVATE):
   if candidate!=allowed and allowed not in candidate.parents: errors.append('private dependency outside bundle/lib')
 return errors
def digest(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for c in iter(lambda:f.read(1048576), b''): h.update(c)
 return h.hexdigest()
def readelf(p): return subprocess.run(['readelf','-d',str(p)],text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT).stdout
def is_elf(p): return subprocess.run(['readelf','-h',str(p)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--bundle',required=True,type=pathlib.Path); ap.add_argument('--manifest',required=True,type=pathlib.Path); a=ap.parse_args(); root=a.bundle.resolve(); m=json.loads(a.manifest.read_text()); errors=[]; actual=[]
 if os.environ.get('LD_LIBRARY_PATH'): errors.append('LD_LIBRARY_PATH must be empty')
 for sec,want in [('bin','$ORIGIN/../lib'),('lib','$ORIGIN')]:
  d=root/sec
  if not d.is_dir(): errors.append('missing '+sec+'/'); continue
  for p in sorted(d.iterdir()):
   if p.is_symlink() or not p.is_file() or not is_elf(p): continue
   rel=str(p.relative_to(root)); actual.append(rel); vals=[]
   for line in readelf(p).splitlines():
    if '(RUNPATH)' in line or '(RPATH)' in line: vals.append(line.split('[',1)[1].split(']',1)[0] if '[' in line else '')
   if vals != [want] or any(not x or x.startswith('/') for x in vals): errors.append(f'bad RPATH {rel}: {vals}')
   out=subprocess.run(['env','-u','LD_LIBRARY_PATH','ldd',str(p)],text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT).stdout
   errors.extend(f'forbidden dependency {rel}: {reason}' for reason in ldd_failures(out, root))
 recorded={x['path'] for x in m.get('canonical_elf',[]) if isinstance(x,dict)}
 if set(actual)!=recorded: errors.append('canonical ELF set mismatch')
 for x in m.get('canonical_elf',[]):
  p=root/x.get('path','')
  if not p.is_file() or p.is_symlink() or p.stat().st_size!=x.get('size') or digest(p)!=x.get('sha256'): errors.append('canonical hash/size mismatch: '+str(x.get('path')))
 for x in m.get('symlinks',[]):
   p=root/x.get('path',''); t=x.get('target',''); pure=pathlib.PurePosixPath(t)
   if not p.is_symlink() or not t or pure.is_absolute() or '..' in pure.parts or not (p.parent/t).exists(): errors.append('unsafe/missing symlink: '+str(x.get('path')))
 actual_links={str(p.relative_to(root)) for sec in ('bin','lib') for p in (root/sec).iterdir() if p.is_symlink()}
 recorded_links={x.get('path') for x in m.get('symlinks',[]) if isinstance(x,dict)}
 if actual_links != recorded_links: errors.append('symlink set mismatch')
 if errors:
  for e in errors: print('FAIL:',e,file=sys.stderr)
  return 1
 print(f'relocatable bundle verification: PASS ({len(actual)} canonical ELF)'); return 0
if __name__=='__main__': raise SystemExit(main())
