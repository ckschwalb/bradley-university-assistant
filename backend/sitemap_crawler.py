import asyncio
import hashlib
import json
import logging
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
from bs4 import BeautifulSoup
from langchain_core.documents import Document

# LangChain imports
from langchain_text_splitters import RecursiveCharacterTextSplitter
from markdownify import markdownify
from sqlmodel import Session, func, select

# Database imports
from clock import utc_iso
from db import engine
from embeddings import embeddings
from models import CrawledDocument

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

WP_API_BASE = "https://www.bradley.edu/wp-json/wp/v2"

# WordPress REST types to index, mapped to the content_type stored on each row
CONTENT_TYPES = {
    "pages": "page",
    "posts": "post",
    "programs": "program",
    "departments": "department",
    "colleges": "college",
    "faculty-staff": "faculty-staff",
}

# The theme renders faculty title, office, phone and email from custom fields that
# the REST API doesn't expose, so these are read from the rendered page instead
HTML_SOURCED_TYPES = {"faculty-staff"}

# Elements that carry styling, icons or UI chrome rather than content. Removing them
# before conversion is what keeps CSS and SVG markup out of the markdown.
NOISE_TAGS = ["style", "script", "svg", "noscript", "iframe", "form", "button", "nav", "header", "footer"]

PAGE_SIZE = 100  # WordPress REST maximum per_page
MIN_CONTENT_CHARS = 20

# Chunk sizing chosen by benchmark (eval/embedding-benchmark/): 3,000 characters ranked
# answers better than 1,500 or 1,000, and each search result gives the chat model more context.
CHUNK_SIZE = 3000
CHUNK_OVERLAP = 400

REQUEST_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; Bradley University AI Assistant Crawler; +https://www.bradley.edu)',
    'Accept-Language': 'en-US,en;q=0.9',
}


class CrawlError(Exception):
    """A request failed after all retries"""


def html_to_markdown(html: str) -> str:
    """Convert page HTML to markdown, dropping styling, icons and images"""
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(NOISE_TAGS):
        tag.decompose()
    for img in soup("img"):
        img.replace_with(img.get("alt") or "")
    text = markdownify(str(soup), heading_style="ATX", bullets="-")
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _parse_json(text: str) -> Any:
    # WordPress plugins occasionally emit an HTML comment before the JSON body
    if text.startswith('<!--'):
        start = min((i for i in (text.find('['), text.find('{')) if i != -1), default=-1)
        text = text[start:] if start != -1 else text
    return json.loads(text)


class SitemapCrawler:
    """Indexes Bradley University web content from the WordPress REST API into the database.

    Each run lists every item of each content type, compares modification times with
    what's stored, and fetches, re-embeds and stores only new or changed items. Rows for
    items that no longer exist are removed. force=True re-processes everything.
    """

    def __init__(self, base_url: str = WP_API_BASE):
        self.base_url = base_url

        # Rate limiting config
        self.rate_limit_delay = 0.5
        self.max_retries = 3
        self.retry_delay_base = 2.0
        self.max_concurrent_page_fetches = 5

        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
            length_function=len,
            separators=["\n\n## ", "\n\n### ", "\n\n", "\n", " ", ""],
        )

    def get_document_count(self) -> int:
        """Get the total number of document chunks in the database"""
        with Session(engine) as session:
            return session.exec(select(func.count(CrawledDocument.id))).one()

    def get_unique_document_count(self) -> int:
        """Get the number of unique documents (not chunks) in the database"""
        with Session(engine) as session:
            return session.exec(select(func.count(func.distinct(CrawledDocument.url)))).one()

    # ---- Fetching -------------------------------------------------------------

    async def _request(self, session: aiohttp.ClientSession, url: str, params: Optional[Dict[str, Any]] = None,
                       as_json: bool = True) -> Tuple[Any, Any]:
        """GET with rate limiting and exponential backoff. Returns (body, headers); raises CrawlError."""
        for attempt in range(self.max_retries):
            await asyncio.sleep(self.rate_limit_delay)
            try:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        text = await response.text()
                        return (_parse_json(text) if as_json else text), response.headers
                    if response.status == 429 or response.status >= 500:
                        reason = f"HTTP {response.status}"
                    else:
                        raise CrawlError(f"HTTP {response.status} for {response.url}")
            except (TimeoutError, aiohttp.ClientError, json.JSONDecodeError) as e:
                reason = str(e) or type(e).__name__

            if attempt < self.max_retries - 1:
                wait_time = self.retry_delay_base * (2 ** attempt)
                logger.warning(f"{reason} for {url}, retrying in {wait_time}s")
                await asyncio.sleep(wait_time)

        raise CrawlError(f"{reason} for {url} after {self.max_retries} attempts")

    async def list_items(self, session: aiohttp.ClientSession, rest_base: str) -> List[Dict[str, Any]]:
        """List every published item of a type as {id, link, modified_gmt}"""
        items = []
        page, total_pages = 1, 1
        while page <= total_pages:
            data, headers = await self._request(session, f"{self.base_url}/{rest_base}", params={
                'per_page': PAGE_SIZE, 'page': page, '_fields': 'id,link,modified_gmt',
            })
            items.extend(data)
            total_pages = int(headers.get('X-WP-TotalPages', 1))
            page += 1
        logger.info(f"Listed {len(items)} {rest_base}")
        return items

    async def _fetch_page_html(self, session: aiohttp.ClientSession, semaphore: asyncio.Semaphore,
                               url: str) -> Optional[str]:
        async with semaphore:
            try:
                html, _ = await self._request(session, url, as_json=False)
                return html
            except CrawlError as e:
                logger.warning(f"Skipping {url}: {e}")
                return None

    async def fetch_items(self, session: aiohttp.ClientSession, rest_base: str,
                          ids: List[int]) -> List[Tuple[Dict[str, Any], str]]:
        """Fetch items by ID, returning (item, html) pairs.

        html is content.rendered, or the full rendered page for HTML-sourced types.
        Items whose page can't be fetched are left out.
        """
        from_page = rest_base in HTML_SOURCED_TYPES
        fields = 'id,link,title,modified_gmt' + ('' if from_page else ',content')
        items, _ = await self._request(session, f"{self.base_url}/{rest_base}", params={
            'include': ','.join(str(i) for i in ids), 'per_page': PAGE_SIZE, '_fields': fields,
        })

        if not from_page:
            return [(item, (item.get('content') or {}).get('rendered') or '') for item in items]

        semaphore = asyncio.Semaphore(self.max_concurrent_page_fetches)
        pages = await asyncio.gather(*(self._fetch_page_html(session, semaphore, item['link']) for item in items))
        return [(item, html) for item, html in zip(items, pages, strict=True) if html is not None]

    # ---- Processing -----------------------------------------------------------

    def build_document(self, item: Dict[str, Any], html: str, rest_base: str) -> Optional[Document]:
        """Turn a fetched item into a markdown Document, or None if it has no real content"""
        title = BeautifulSoup((item.get('title') or {}).get('rendered') or '', 'lxml').get_text().strip() or 'Untitled'

        if rest_base in HTML_SOURCED_TYPES:
            soup = BeautifulSoup(html, 'lxml')
            html = str(soup.find('main') or soup.find('article') or '')
        body = html_to_markdown(html)
        if len(body) < MIN_CONTENT_CHARS:
            return None

        # The title leads the text so it's part of what gets embedded (e.g. a person's name)
        text = f"# {title}\n\n{body}"
        return Document(page_content=text, metadata={
            'source': item['link'],
            'title': title,
            'wp_id': item['id'],
            'wp_type': rest_base,
            'modified_gmt': item.get('modified_gmt'),
            'content_hash': hashlib.sha256(text.encode('utf-8')).hexdigest(),
        })

    def _build_documents(self, fetched: List[Tuple[Dict[str, Any], str]],
                         rest_base: str) -> Tuple[List[Document], List[str]]:
        """Returns (documents, links of items with no usable content)"""
        documents, empty = [], []
        for item, html in fetched:
            try:
                document = self.build_document(item, html, rest_base)
            except Exception as e:
                logger.error(f"Error processing {item.get('link')}: {e}")
                continue
            if document:
                documents.append(document)
            else:
                empty.append(item['link'])
        return documents, empty

    # ---- Storage --------------------------------------------------------------

    def _load_stored_state(self) -> Tuple[Dict[str, Dict[str, Any]], set]:
        """Returns ({url: first-chunk doc_metadata}, every non-course url) for web content"""
        with Session(engine) as session:
            rows = session.exec(
                select(CrawledDocument.url, CrawledDocument.chunk_index, CrawledDocument.doc_metadata)
                .where(CrawledDocument.content_type != "course")
            ).all()
        state = {url: (meta or {}) for url, chunk_index, meta in rows if chunk_index == 0}
        return state, {url for url, _, _ in rows}

    def split_document(self, document: Document) -> List[Document]:
        """Split into chunks, repeating the page title on every chunk so later chunks
        still say what page they come from (e.g. whose office hours these are)"""
        chunks = self.text_splitter.split_documents([document])
        header = f"# {document.metadata['title']}\n\n"
        for chunk in chunks[1:]:
            chunk.page_content = header + chunk.page_content
        return chunks

    def _store_documents(self, entries: List[Tuple[Document, str, List[Document], List[bytes]]]):
        """Replace each document's rows with its new chunks. entries: (doc, content_type, chunks, vectors)"""
        with Session(engine) as session:
            for document, content_type, chunks, vectors in entries:
                url = document.metadata['source']
                for row in session.exec(select(CrawledDocument).where(CrawledDocument.url == url)).all():
                    session.delete(row)
                for i, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True)):
                    session.add(CrawledDocument(
                        url=url,
                        title=document.metadata['title'],
                        content=chunk.page_content,
                        content_type=content_type,
                        embedding=vector,
                        doc_metadata=document.metadata,
                        chunk_index=i,
                        total_chunks=len(chunks),
                    ))
            session.commit()

    def _touch_documents(self, documents: List[Document]):
        """Record the new modified_gmt for documents whose text didn't change, without re-embedding"""
        with Session(engine) as session:
            for document in documents:
                for row in session.exec(select(CrawledDocument).where(CrawledDocument.url == document.metadata['source'])).all():
                    row.doc_metadata = document.metadata
                    session.add(row)
            session.commit()

    def _delete_urls(self, urls: List[str]):
        with Session(engine) as session:
            for url in urls:
                for row in session.exec(select(CrawledDocument).where(CrawledDocument.url == url)).all():
                    session.delete(row)
            session.commit()

    # ---- Orchestration --------------------------------------------------------

    async def _process_batch(self, session: aiohttp.ClientSession, rest_base: str, ids: List[int],
                             stored: Dict[str, Dict[str, Any]], force: bool, stats: Dict[str, int]) -> List[str]:
        """Fetch, embed and store one batch of changed items. Returns links of items with no usable content."""
        fetched = await self.fetch_items(session, rest_base, ids)
        documents, empty = await asyncio.to_thread(self._build_documents, fetched, rest_base)
        stats['items_empty'] += len(empty)

        unchanged, to_embed = [], []
        for d in documents:
            same_text = stored.get(d.metadata['source'], {}).get('content_hash') == d.metadata['content_hash']
            (unchanged if same_text and not force else to_embed).append(d)
        if unchanged:
            await asyncio.to_thread(self._touch_documents, unchanged)
            stats['documents_unchanged'] += len(unchanged)
        if not to_embed:
            return empty

        chunked = [(d, self.split_document(d)) for d in to_embed]
        texts = [c.page_content for _, chunks in chunked for c in chunks]
        vectors = await asyncio.to_thread(embeddings.embed_documents_bytes, texts)

        entries, offset = [], 0
        for document, chunks in chunked:
            entries.append((document, CONTENT_TYPES[rest_base], chunks, vectors[offset:offset + len(chunks)]))
            offset += len(chunks)
        await asyncio.to_thread(self._store_documents, entries)
        stats['documents_stored'] += len(entries)
        stats['chunks_stored'] += len(texts)
        return empty

    async def crawl_all_content(self, force: bool = False) -> Dict[str, Any]:
        """Sync WordPress content into the database. Only new or changed items are fetched and embedded
        unless force=True. Returns run statistics, or {'error': ...} if nothing could be listed."""
        logger.info(f"Starting Bradley University content crawl (force={force})")
        start_time = time.time()

        stored, stored_urls = await asyncio.to_thread(self._load_stored_state)
        stats = {k: 0 for k in ('items_listed', 'items_changed', 'items_empty', 'documents_stored',
                                'documents_unchanged', 'documents_deleted', 'chunks_stored', 'batches_failed')}
        live_urls, empty_urls, failed_types = set(), set(), []

        timeout = aiohttp.ClientTimeout(total=120)
        async with aiohttp.ClientSession(headers=REQUEST_HEADERS, timeout=timeout) as session:
            for rest_base in CONTENT_TYPES:
                try:
                    listing = await self.list_items(session, rest_base)
                except CrawlError as e:
                    logger.error(f"Could not list {rest_base}: {e}")
                    failed_types.append(rest_base)
                    continue

                live_urls.update(item['link'] for item in listing)
                changed = [item for item in listing
                           if force or stored.get(item['link'], {}).get('modified_gmt') != item['modified_gmt']]
                stats['items_listed'] += len(listing)
                stats['items_changed'] += len(changed)
                logger.info(f"{rest_base}: {len(changed)} of {len(listing)} new or changed")

                for i in range(0, len(changed), PAGE_SIZE):
                    ids = [item['id'] for item in changed[i:i + PAGE_SIZE]]
                    try:
                        empty_urls.update(await self._process_batch(session, rest_base, ids, stored, force, stats))
                    except Exception as e:
                        # Items in a failed batch keep their old rows and old modified_gmt, so the next run retries them
                        logger.error(f"Failed {rest_base} batch {i // PAGE_SIZE + 1}: {e}")
                        stats['batches_failed'] += 1

        if len(failed_types) == len(CONTENT_TYPES):
            return {'error': 'Could not list any WordPress content'}

        # Only prune when every type was listed; otherwise a failed listing would look like mass deletion
        if not failed_types:
            stale = sorted(stored_urls - (live_urls - empty_urls))
            if stale:
                await asyncio.to_thread(self._delete_urls, stale)
                logger.info(f"Removed {len(stale)} documents that no longer exist")
            stats['documents_deleted'] = len(stale)

        result = {
            **stats,
            'total_documents': self.get_unique_document_count(),
            'failed_types': failed_types,
            'duration_seconds': round(time.time() - start_time, 1),
            'timestamp': utc_iso(),
        }
        logger.info(f"Crawl completed: {result}")
        return result


# Global crawler instance
crawler = SitemapCrawler()

if __name__ == "__main__":
    async def main():
        """Run the crawler. Pass --force to re-fetch and re-embed everything."""
        logger.info("Starting Bradley University content crawler...")

        try:
            result = await crawler.crawl_all_content(force="--force" in sys.argv)

            if 'error' in result:
                logger.error(f"Crawler failed: {result['error']}")
                return

            logger.info("Crawler completed successfully!")

        except Exception as e:
            logger.error(f"Crawler error: {e}")
            import traceback
            traceback.print_exc()

    # Run the crawler
    asyncio.run(main())
