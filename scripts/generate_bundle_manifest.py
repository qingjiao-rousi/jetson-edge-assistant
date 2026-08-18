#!/usr/bin/env python3
"""Generate and validate a relocatable EdgeOmni bundle manifest."""
from __future__ import annotations
import argparse, hashlib, json, os, pathlib, subprocess, sys
import re

PRIVATE = ("libggml", "libllama", "libmtmd", "libomni")

def ldd_failures(output: str, root: pathlib.Path) -> list[str]:
    failures=[]; allowed=(root / "lib").resolve()
    for line in output.splitlines():
        if "not found" in line: failures.append("not found"); continue
        match=re.search(r"=>\s+(\S+)", line)
        if not match: continue
        candidate=pathlib.Path(match.group(1)).resolve(strict=False)
        if any(name in line for name in PRIVATE):
            if allowed not in candidate.parents and candidate != allowed: failures.append("private dependency outside bundle/lib")
    return failures

def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""): h.update(chunk)
    return h.hexdigest()

def elf(path: pathlib.Path) -> bool:
    return subprocess.run(["readelf", "-h", str(path)], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0

def dynamic(path: pathlib.Path) -> str:
    return subprocess.run(["readelf", "-d", str(path)], check=True, text=True,
                          stdout=subprocess.PIPE).stdout

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--bundle", required=True, type=pathlib.Path)
    p.add_argument("--output", required=True, type=pathlib.Path)
    a = p.parse_args(); root = a.bundle.resolve()
    if not (root / "bin").is_dir() or not (root / "lib").is_dir():
        print("bundle must contain bin/ and lib/", file=sys.stderr); return 2
    files=[]; failures=[]
    for section, expected in (("bin", "$ORIGIN/../lib"), ("lib", "$ORIGIN")):
        for path in sorted((root / section).iterdir()):
            if path.is_symlink() or not path.is_file() or not elf(path): continue
            text=dynamic(path); entries=[]
            for line in text.splitlines():
                if "(RUNPATH)" in line or "(RPATH)" in line:
                    entries.append(line.split("[",1)[1].split("]",1)[0])
            if entries != [expected] or any(not x or x.startswith("/") for x in entries): failures.append(str(path)+":rpath")
            ldd=subprocess.run(["env", "-u", "LD_LIBRARY_PATH", "ldd", str(path)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT).stdout
            for reason in ldd_failures(ldd, root): failures.append(str(path)+":ldd:"+reason)
            files.append({"path": str(path.relative_to(root)), "size": path.stat().st_size,
                          "sha256": sha256(path), "rpath": entries[0] if entries else None})
    links=[{"path": str(p.relative_to(root)), "target": p.readlink().as_posix()}
           for section in ("bin","lib") for p in sorted((root/section).iterdir()) if p.is_symlink()]
    try:
        commit=subprocess.run(["git","rev-parse","HEAD"],check=True,text=True,stdout=subprocess.PIPE).stdout.strip()
        upstream=subprocess.run(["git","-C","third_party/llama.cpp-omni","rev-parse","HEAD"],check=True,text=True,stdout=subprocess.PIPE).stdout.strip()
    except (OSError, subprocess.CalledProcessError): commit=upstream=None
    data={"schema_version":1,"edgeomni_commit":commit,"upstream_commit":upstream,
          "options":{"BUILD_SHARED_LIBS":True,"GGML_CUDA":True,"GGML_CUDA_NCCL":False,
                      "GGML_BACKEND_DL":False,"CMAKE_BUILD_RPATH_USE_ORIGIN":True},
          "canonical_elf":files,"symlinks":links,
          "audit":{"rpath":"pass" if not failures else "fail","ldd":"pass" if not failures else "fail"},
          "status":"pass" if not failures else "fail"}
    a.output.parent.mkdir(parents=True, exist_ok=True); a.output.write_text(json.dumps(data,indent=2)+"\n")
    print(json.dumps({"status":data["status"],"canonical_elf":len(files),"symlinks":len(links)},sort_keys=True))
    return 0 if not failures else 1
if __name__ == "__main__": raise SystemExit(main())
