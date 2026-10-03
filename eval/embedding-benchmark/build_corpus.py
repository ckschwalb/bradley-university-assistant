"""Fetch and clean all bradley.edu content with the production crawler code, without storing it.

    python build_corpus.py corpus.json
"""
import asyncio, json, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
sys.path.insert(0, os.path.join(HERE, "..", "..", "backend"))
import aiohttp, sitemap_crawler as sc
c = sc.crawler
async def main():
    t = time.time(); docs = []
    async with aiohttp.ClientSession(headers=sc.REQUEST_HEADERS, timeout=aiohttp.ClientTimeout(total=120)) as s:
        for rb in ["pages", "posts", "programs", "departments", "colleges", "faculty-staff"]:
            listing = await c.list_items(s, rb)
            for i in range(0, len(listing), 100):
                fetched = await c.fetch_items(s, rb, [x["id"] for x in listing[i:i+100]])
                built, _ = await asyncio.to_thread(c._build_documents, fetched, rb)
                docs += [{"url": d.metadata["source"], "title": d.metadata["title"], "type": rb, "text": d.page_content} for d in built]
            print(rb, len(listing), f"{time.time()-t:.0f}s", flush=True)
    json.dump(docs, open(sys.argv[1], "w"))
    print("docs", len(docs), "chars", sum(len(d["text"]) for d in docs))
asyncio.run(main())
