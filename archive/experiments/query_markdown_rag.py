#!/usr/bin/env python3
"""Query the M9.1A SQLite FTS5 index and return source-grounded chunks."""
import argparse, json, pathlib, re, sqlite3

STOP={"a","an","and","be","does","how","is","it","long","of","should","the","what","when"}
def query_terms(query):return [term.lower() for term in re.findall(r"[A-Za-z0-9]+",query) if term.lower() not in STOP and len(term)>1]
def query_index(database,query,top_k):
    terms=query_terms(query)
    response={"query":query,"answerable":False,"top_k":top_k,"results":[],"citations":[]}
    if not terms:return response
    expression=" OR ".join(f'"{term}"' for term in terms)
    connection=sqlite3.connect(database);connection.row_factory=sqlite3.Row
    try:rows=connection.execute("SELECT c.* FROM chunks_fts f JOIN chunks c ON c.chunk_id=f.chunk_id WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts), c.ordinal LIMIT ?",(expression,top_k)).fetchall()
    finally:connection.close()
    for row in rows:
        citation=json.loads(row["citation_json"]);response["results"].append({"chunk_id":row["chunk_id"],"document_id":row["document_id"],"heading":row["heading"],"ordinal":row["ordinal"],"text":row["text"],"text_sha256":row["text_sha256"],"token_count":row["token_count"],"citation":citation});response["citations"].append(citation)
    response["answerable"]=bool(response["results"]);return response
def main():
    parser=argparse.ArgumentParser();parser.add_argument("--database",required=True);parser.add_argument("--query",required=True);parser.add_argument("--top-k",type=int,default=3);args=parser.parse_args()
    if args.top_k<1:raise SystemExit("top-k must be positive")
    print(json.dumps(query_index(pathlib.Path(args.database),args.query,args.top_k),indent=2))
if __name__=="__main__":main()
