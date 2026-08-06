#!/usr/bin/env python3
"""Build the deterministic M9.1A Markdown/SQLite FTS5 keyword index."""
import argparse, hashlib, json, pathlib, re, sqlite3, subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
HEADING_RE = re.compile(r"^##\s+(.+?)\s*$")
META_RE = re.compile(r"^(Document ID|Revision|Language|Classification):\s*(.+?)\s*$")

def sha256_text(text): return hashlib.sha256(text.encode("utf-8")).hexdigest()
def slugify(value): return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")

def parse_manual(path):
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or not lines[0].startswith("# "): raise ValueError("manual requires one H1 title")
    metadata = {}
    for line in lines[1:]:
        match = META_RE.match(line)
        if match: metadata[match.group(1)] = match.group(2)
        if HEADING_RE.match(line): break
    required = {"Document ID", "Revision", "Language", "Classification"}
    if set(metadata) != required: raise ValueError("manual metadata is incomplete")
    sections=[]; heading=None; body=[]
    def append_section():
        if heading is None:return
        section_text="\n".join(body).strip()
        if not section_text:raise ValueError(f"empty section: {heading}")
        ordinal=len(sections)+1;chunk_id=f"{metadata['Document ID']}#{slugify(heading)}"
        sections.append({"chunk_id":chunk_id,"document_id":metadata["Document ID"],"heading":heading,"ordinal":ordinal,"text":section_text,"text_sha256":sha256_text(section_text),"citation":{"document_id":metadata["Document ID"],"chunk_id":chunk_id,"source":path.name,"section":heading}})
    for line in lines:
        match=HEADING_RE.match(line)
        if match:append_section();heading=match.group(1);body=[]
        elif heading is not None:body.append(line)
    append_section()
    document={"document_id":metadata["Document ID"],"revision":metadata["Revision"],"source_path":path.relative_to(ROOT).as_posix(),"content_sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"title":lines[0][2:].strip(),"language":metadata["Language"],"classification":metadata["Classification"]}
    return document,sections

def token_count(binary, model, text):
    command=[str(binary),"--model",str(model),"--stdin","--ids","--no-bos","--log-disable"]
    result=subprocess.run(command,input=text,text=True,capture_output=True,check=False)
    if result.returncode != 0: raise RuntimeError(f"tokenizer failed with exit code {result.returncode}: {result.stderr.strip()}")
    try: tokens=json.loads(result.stdout.strip())
    except json.JSONDecodeError as error: raise RuntimeError("tokenizer output is not a token ID array") from error
    if not isinstance(tokens,list) or not all(isinstance(token,int) for token in tokens):raise RuntimeError("tokenizer output is not a token ID array")
    return len(tokens)

def build_index(source,database,tokenizer,model):
    document,chunks=parse_manual(source)
    for chunk in chunks:chunk["token_count"]=token_count(tokenizer,model,chunk["text"])
    database.parent.mkdir(parents=True,exist_ok=True)
    if database.exists():database.unlink()
    connection=sqlite3.connect(database)
    try:
        connection.executescript("""
        CREATE TABLE documents(document_id TEXT PRIMARY KEY, revision TEXT NOT NULL, source_path TEXT NOT NULL, content_sha256 TEXT NOT NULL, title TEXT NOT NULL, language TEXT NOT NULL, classification TEXT NOT NULL);
        CREATE TABLE chunks(chunk_id TEXT PRIMARY KEY, document_id TEXT NOT NULL, heading TEXT NOT NULL, ordinal INTEGER NOT NULL, text TEXT NOT NULL, text_sha256 TEXT NOT NULL, token_count INTEGER NOT NULL, citation_json TEXT NOT NULL);
        CREATE VIRTUAL TABLE chunks_fts USING fts5(chunk_id UNINDEXED, heading, text, tokenize='porter unicode61');
        """)
        connection.execute("INSERT INTO documents VALUES(?,?,?,?,?,?,?)",tuple(document.values()))
        for chunk in chunks:
            connection.execute("INSERT INTO chunks VALUES(?,?,?,?,?,?,?,?)",(chunk["chunk_id"],chunk["document_id"],chunk["heading"],chunk["ordinal"],chunk["text"],chunk["text_sha256"],chunk["token_count"],json.dumps(chunk["citation"],sort_keys=True,separators=(",",":"))))
            connection.execute("INSERT INTO chunks_fts VALUES(?,?,?)",(chunk["chunk_id"],chunk["heading"],chunk["text"]))
        connection.commit()
    finally:connection.close()
    return {"document":document,"chunks":chunks,"database_path":str(database),"database_size_bytes":database.stat().st_size}

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--source",default="knowledge/manuals/ax17-equipment-manual.md");parser.add_argument("--database",required=True);parser.add_argument("--tokenizer",default="third_party/llama.cpp-omni/build-jetson-release/bin/llama-tokenize");parser.add_argument("--model",default="models/Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf");parser.add_argument("--manifest")
    args=parser.parse_args();manifest=build_index(ROOT/args.source,pathlib.Path(args.database),ROOT/args.tokenizer,ROOT/args.model)
    if args.manifest:pathlib.Path(args.manifest).write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(manifest,sort_keys=True))
if __name__=="__main__":main()
