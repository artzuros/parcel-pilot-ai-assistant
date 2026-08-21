import json, pathlib, re

from rank_bm25 import BM25Okapi


HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
EXTRACTED_DIR = ROOT / "data" / "extracted_text"
DOCS_META = json.loads((HERE / "docs_meta.json").read_text(encoding="utf-8"))

AUTHORITY_WEIGHT = {
    "agreement": 1.3,
    "sop": 1.15,
    "policy": 1.0,
    "product": 0.9,
    "DEPRECATED": 0.25,
}

def tokenize(text):
    return re.findall(r"[a-z0-9]+", (text or "".lower()))

def _chunk_text(text, max_len=500):
    chunks = []
    for raw in re.split(r"\n\s*\n", text):
        para = " ".join(line.strip() for line in raw.splitlines() if line.strip())
        if not para: continue
        while len(para) > max_len:
            cut = para.rfind(" ", 0, max_len)
            cut = cut if cut > 0 else max_len
            chunks.append(para[:cut].strip())
            para = para[cut:].strip()
        if para:
            chunks.append(para)
    return chunks

def _weight(meta):
    if meta.get("status") == "DEPRECATED":
        return AUTHORITY_WEIGHT["DEPRECATED"]
    return AUTHORITY_WEIGHT.get(meta.get("kind", ""), 1.0)

def build_index(extracted_dir=None):
    extracted_dir = pathlib.Path(extracted_dir) if extracted_dir else EXTRACTED_DIR
    chunks = []
    for path in sorted(extracted_dir.glob("*.txt")):
        doc_id = path.stem
        meta = DOCS_META.get(doc_id, {"status": "UNKNOWN",
                                      "kind": "unknown",
                                      "title": doc_id
                                      })
        for i, text in enumerate(_chunk_text(path.read_text(encoding="utf-8"))):
            chunks.append({
                "doc_id": doc_id,
                "title": meta.get("title", doc_id),
                "status": meta.get("status", "UNKNOWN"),
                "effective": meta.get("effective") or meta.get("updated"),
                "kind": meta.get("kind", "unknown"),
                "section": f"chunk {i}",
                "text": text,
            })
    return {"chunks": chunks, "index": BM25Okapi([tokenize(c["text"]) for c in chunks])}



class DocSearch:
    def __init__(self, extracted_dir):
        built = build_index(extracted_dir)
        self.chunks = built["chunks"]
        self.index = built["index"]
        
    def search(self, query, max_results=4):
        tokens = tokenize(query)
        if not tokens:
            return []
        results = []
        for chunk, score in zip(self.chunks, self.index.get_scores(tokens)):
            if score <= 0:
                continue
            meta = DOCS_META.get(chunk["doc_id"], {})
            results.append({**chunk, "score": round(score * _weight(meta), 3)})
        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:max_results]