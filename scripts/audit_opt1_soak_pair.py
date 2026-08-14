#!/usr/bin/env python3
"""Audit paired formal OPT-1 soak evidence, including cross-mode output identity."""
from __future__ import annotations
import argparse,json,pathlib,re,statistics,sys
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"scripts"))
from audit_opt1_soak import audit as audit_single

def trend(raw,path):
    log=pathlib.Path(raw.get("tegrastats_log") or path.with_suffix(".tegrastats.log"))
    text=log.read_text(encoding="utf-8",errors="replace") if log.is_file() else ""
    ram=[int(value) for value in re.findall(r"RAM (\d+)/",text)]
    size=max(1,(len(ram)+4)//5)
    return {"samples":len(ram),"ram_used_mb":{"first_20_percent_median":statistics.median(ram[:size]),"last_20_percent_median":statistics.median(ram[-size:]),"peak":max(ram)} if ram else {},"unified_ram_is_not_a_kv_leak_proof":True}
def response_shape(raw):
    rows=raw.get("requests",[])
    return {key:sorted({r.get("response",{}).get(key) for r in rows}) for key in ("prompt_tokens","output_tokens","finish_reason")}
def audit_pair(disabled,hot,disabled_path=pathlib.Path("disabled.json"),hot_path=pathlib.Path("hot.json"),duration_ratio=.95):
    failures=[];d=audit_single(disabled);h=audit_single(hot)
    if d["status"]!="PASS":failures.append("disabled_single_audit")
    if h["status"]!="PASS":failures.append("single_hot_single_audit")
    for raw,name in ((disabled,"disabled"),(hot,"single_hot")):
        if raw.get("status")!="UNREVIEWED_RAW_RESULT":failures.append(f"{name}_not_formal_raw")
        requested=raw.get("requested_minutes");duration=raw.get("measured_duration_seconds")
        if not isinstance(requested,(int,float)) or not isinstance(duration,(int,float)) or duration<requested*60*duration_ratio:failures.append(f"{name}_duration_insufficient")
    for key in ("commit","model_sha256","mmproj_sha256","prompt_sha256","clock_locked","clock_detail","clock_output","runtime_parameters"):
        if disabled.get(key)!=hot.get(key):failures.append(f"provenance_mismatch:{key}")
    if disabled.get("mode")!="disabled" or hot.get("mode")!="single_hot_text":failures.append("mode_mismatch")
    ds,hs=response_shape(disabled),response_shape(hot)
    if ds!=hs:failures.append("response_shape_mismatch")
    if d["unique_output_hashes"]!=1 or h["unique_output_hashes"]!=1:failures.append("within_mode_output_not_deterministic")
    d_hash={r.get("text_sha256") for r in disabled.get("requests",[])};h_hash={r.get("text_sha256") for r in hot.get("requests",[])}
    if d_hash!=h_hash:failures.append("cross_mode_output_hash_mismatch")
    resource={"disabled":trend(disabled,disabled_path),"single_hot":trend(hot,hot_path)}
    if not resource["disabled"]["samples"] or not resource["single_hot"]["samples"]:failures.append("tegrastats_missing_or_unparseable")
    return {"status":"PASS" if not failures else "FAIL","fail_reasons":sorted(set(failures)),"disabled":d,"single_hot":h,"response_shape":{"disabled":ds,"single_hot":hs},"resource_trend":resource,"unified_ram_is_not_a_kv_leak_proof":True}
def main():
    p=argparse.ArgumentParser();p.add_argument("disabled",type=pathlib.Path);p.add_argument("single_hot",type=pathlib.Path);p.add_argument("--minimum-duration-ratio",type=float,default=.95);a=p.parse_args()
    if not 0<a.minimum_duration_ratio<=1:p.error("--minimum-duration-ratio must be in (0, 1]")
    try:r=audit_pair(json.loads(a.disabled.read_text()),json.loads(a.single_hot.read_text()),a.disabled,a.single_hot,a.minimum_duration_ratio)
    except (OSError,TypeError,ValueError,json.JSONDecodeError) as error:print(f"paired soak audit failed: {error}",file=sys.stderr);return 1
    print(json.dumps(r,indent=2));return 0 if r["status"]=="PASS" else 1
if __name__=="__main__":raise SystemExit(main())
