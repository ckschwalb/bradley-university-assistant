"""Compare local embedding models and chunk sizes on bradley.edu content.

    pip install fastembed rank_bm25 langchain-text-splitters numpy
    python build_corpus.py corpus.json      # ~4 minutes
    python bench.py                          # all models and configs
    python bench.py arctic-embed-s           # only models whose name contains this

Metrics per question set (questions.json: question -> page(s) that answer it):
  r5   share of questions where a correct page is among the top 5 chunks (what the chat model sees)
  mrr  mean reciprocal rank of the first correct page among the top 10 distinct pages
"""
import json, os, re, sys, time
import numpy as np
from langchain_text_splitters import RecursiveCharacterTextSplitter
from rank_bm25 import BM25Okapi
from fastembed import TextEmbedding

BASE = "https://www.bradley.edu"
HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
docs = json.load(open("corpus.json"))
questions = json.load(open("questions.json"))
Q = "Represent this sentence for searching relevant passages: "
MODELS = {  # name: (query prefix, document prefix)
    "sentence-transformers/all-MiniLM-L6-v2": ("", ""),
    "minishlab/potion-retrieval-32M": ("", ""),
    "BAAI/bge-small-en-v1.5": (Q, ""),
    "snowflake/snowflake-arctic-embed-s": (Q, ""),
    "jinaai/jina-embeddings-v2-small-en": ("", ""),
    "nomic-ai/nomic-embed-text-v1.5-Q": ("search_query: ", "search_document: "),
    "BAAI/bge-base-en-v1.5": (Q, ""),
}
CONFIGS = {"3000 plain (current)": (3000, 400, False), "3000 + title": (3000, 400, True), "1500 + title": (1500, 200, True), "1000 + title": (1000, 150, True)}

def chunk(size, overlap, title_header):
    sp = RecursiveCharacterTextSplitter(chunk_size=size, chunk_overlap=overlap,
                                        separators=["\n\n## ", "\n\n### ", "\n\n", "\n", " ", ""])
    out = []
    for d in docs:
        for i, c in enumerate(sp.split_text(d["text"])):
            text = c if (not title_header or i == 0) else f"# {d['title']}\n\n{c}"
            out.append((d["url"].replace(BASE, ""), text))
    return out

def evaluate(rank_fn, chunk_urls):
    hits5, rr = 0, 0.0
    for q, targets in questions:
        order = rank_fn(q)
        top5 = {chunk_urls[i] for i in order[:5]}
        hits5 += bool(top5 & set(targets))
        seen = []
        for i in order[:50]:
            u = chunk_urls[i]
            if u not in seen: seen.append(u)
            if len(seen) == 10: break
        rank = next((k + 1 for k, u in enumerate(seen) if u in targets), None)
        rr += 1 / rank if rank else 0
    return hits5 / len(questions), rr / len(questions)

def rrf(*orders, k=60):
    score = {}
    for order in orders:
        for r, i in enumerate(order[:200]):
            score[i] = score.get(i, 0) + 1 / (k + r)
    return sorted(score, key=score.get, reverse=True)

tok = lambda t: re.findall(r"\w+", t.lower())
results = []
only = sys.argv[1:]  # optional model filter
for cname, (size, overlap, header) in CONFIGS.items():
    chunks = chunk(size, overlap, header)
    urls = [u for u, _ in chunks]; texts = [t for _, t in chunks]
    bm25 = BM25Okapi([tok(t) for t in texts])
    bm25_rank = lambda q: list(np.argsort(-bm25.get_scores(tok(q))))
    bm25_orders = {q: bm25_rank(q) for q, _ in questions}
    r5, mrr = evaluate(lambda q: bm25_orders[q], urls)
    results.append(dict(config=cname, model="BM25 (keyword only)", chunks=len(chunks), r5=r5, mrr=mrr))
    print(results[-1], flush=True)
    for name, (qp, dp) in MODELS.items():
        if only and not any(o in name for o in only): continue
        cache = f"cache/{name.replace('/', '_')}_{size}_{int(header)}.npy"
        m = TextEmbedding(name)
        t0 = time.time()
        if os.path.exists(cache):
            E = np.load(cache); rate = None
        else:
            os.makedirs("cache", exist_ok=True)
            E = np.array(list(m.embed([dp + t for t in texts], batch_size=32)), dtype=np.float32)
            rate = len(texts) / (time.time() - t0); np.save(cache, E)
        E /= np.linalg.norm(E, axis=1, keepdims=True)
        qv = np.array(list(m.embed([qp + q for q, _ in questions])), dtype=np.float32)
        qv /= np.linalg.norm(qv, axis=1, keepdims=True)
        dense_orders = {q: list(np.argsort(-(E @ qv[j]))) for j, (q, _) in enumerate(questions)}
        r5, mrr = evaluate(lambda q: dense_orders[q], urls)
        h5, hmrr = evaluate(lambda q: rrf(dense_orders[q], bm25_orders[q]), urls)
        t0 = time.time(); list(m.embed([qp + "When is the add/drop deadline?"])); qlat = (time.time() - t0) * 1000
        results.append(dict(config=cname, model=name, dim=E.shape[1], chunks=len(chunks), r5=r5, mrr=mrr,
                            hybrid_r5=h5, hybrid_mrr=hmrr, chunks_per_s=rate, query_ms=round(qlat, 1),
                            index_mb=round(E.nbytes / 1e6, 1)))
        print(results[-1], flush=True)
        json.dump(results, open("results.json", "w"), indent=1)
json.dump(results, open("results.json", "w"), indent=1)
print("DONE")
