from app.retrieval.index import DocSearch, EXTRACTED_DIR

_search = None

def get_search():
    global _search
    if _search is None:
        _search = DocSearch(EXTRACTED_DIR)
    return _search

def doc_search_tool(query, max_results=4):
    results = get_search().search(query, max_results=max_results or 4)
    return {
        "status": "ok",
        "query": query,
        "count": len(results),
        "results": [
            {
                "doc_id": r["doc_id"],
                "title": r["title"],
                "status": r["status"],
                "effective": r["effective"],
                "score": r["score"],
                "snippet": r["text"][:300],
            } for r in results
        ],
    }
    