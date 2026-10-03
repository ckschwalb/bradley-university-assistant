import asyncio
import hashlib
import logging
import re
from typing import Any, Dict, List, Optional

import aiohttp
from bs4 import BeautifulSoup

# LangChain imports
from langchain_core.documents import Document
from sqlmodel import Session, func, select

# Database imports
from clock import utc_iso
from db import engine
from embeddings import embeddings
from models import CrawledDocument

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class CourseCatalogCrawler:
    """Handles crawling and indexing of Bradley University course catalog"""

    def __init__(self):
        # Rate limiting config
        self.rate_limit_delay = 0.5
        self.max_retries = 3
        self.retry_delay_base = 2.0

        # Catalog sitemap URL
        self.catalog_sitemap_url = "https://catalog.bradley.edu/sitemap.xml"

    def _stored_hashes(self) -> Dict[str, Optional[str]]:
        """{course url: content hash} for courses already in the database"""
        with Session(engine) as session:
            rows = session.exec(
                select(CrawledDocument.url, CrawledDocument.doc_metadata).where(CrawledDocument.content_type == "course")
            ).all()
        return {url: (meta or {}).get('content_hash') for url, meta in rows}

    def store_courses(self, course_docs: List[Document]) -> int:
        """Embed and store courses, replacing any existing rows for the same URLs"""
        course_docs = [d for d in course_docs if d.page_content and len(d.page_content.strip()) >= 20]
        if not course_docs:
            return 0
        vectors = embeddings.embed_documents_bytes([d.page_content for d in course_docs])
        with Session(engine) as session:
            for doc, vector in zip(course_docs, vectors, strict=True):
                source_url = doc.metadata['source']
                for row in session.exec(select(CrawledDocument).where(CrawledDocument.url == source_url)).all():
                    session.delete(row)
                # Courses are short, so each is stored as a single chunk
                session.add(CrawledDocument(
                    url=source_url,
                    title=doc.metadata.get('title', 'Unknown Course'),
                    content=doc.page_content,
                    content_type="course",
                    embedding=vector,
                    doc_metadata=doc.metadata,
                    chunk_index=0,
                    total_chunks=1,
                ))
            session.commit()
        return len(course_docs)

    def get_course_count(self) -> int:
        """Get the total number of courses in the database"""
        with Session(engine) as session:
            return session.exec(
                select(func.count(CrawledDocument.id)).where(CrawledDocument.content_type == "course")
            ).one()

    async def parse_catalog_sitemap(self, session: aiohttp.ClientSession) -> List[str]:
        """Parse the catalog sitemap to extract course description page URLs"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (compatible; Bradley University AI Assistant Crawler; +https://www.bradley.edu)',
                'Accept': 'application/xml, text/xml, */*',
            }

            async with session.get(self.catalog_sitemap_url, headers=headers) as response:
                if response.status != 200:
                    logger.warning(f"Failed to fetch catalog sitemap: HTTP {response.status}")
                    return []

                xml_content = await response.text()

                # Parse XML
                import xml.etree.ElementTree as ET
                root = ET.fromstring(xml_content)

                # Handle XML namespaces
                namespaces = {
                    'sitemap': 'http://www.sitemaps.org/schemas/sitemap/0.9'
                }

                course_urls = []

                # Find all URL elements
                for url_elem in root.findall('.//sitemap:url', namespaces):
                    loc_elem = url_elem.find('sitemap:loc', namespaces)
                    if loc_elem is not None and loc_elem.text:
                        url = loc_elem.text.strip()
                        # Filter for course description pages
                        if '/course-descriptions/' in url:
                            course_urls.append(url)

                # If no URLs found with namespace, try without namespace
                if not course_urls:
                    for url_elem in root.findall('.//url'):
                        loc_elem = url_elem.find('loc')
                        if loc_elem is not None and loc_elem.text:
                            url = loc_elem.text.strip()
                            if '/course-descriptions/' in url:
                                course_urls.append(url)

                logger.info(f"Found {len(course_urls)} course description pages in sitemap")
                return course_urls

        except Exception as e:
            logger.error(f"Error parsing catalog sitemap: {e}")
            return []

    def extract_prerequisite_courses(self, prerequisite_text: str) -> List[str]:
        """Extract course codes from prerequisite text"""
        if not prerequisite_text or prerequisite_text.strip() == "":
            return []

        # Pattern to match course codes like "CS 101", "MTH 109", etc.
        # Matches: 2-4 letter subject code, space, 3-4 digit number
        pattern = r'\b([A-Z]{2,4})\s+(\d{3,4})\b'
        matches = re.findall(pattern, prerequisite_text)

        # Format as "CS 101"
        courses = [f"{subject} {number}" for subject, number in matches]
        return courses

    def parse_course_block(self, course_block: BeautifulSoup, subject_url: str, level: str) -> Optional[Document]:
        """Parse a single course block into a Document"""
        try:
            # Extract course title block
            title_block = course_block.find('p', class_='courseblocktitle')
            if not title_block:
                return None

            # Extract course code and title
            spans = title_block.find_all('span')
            if len(spans) < 2:
                return None

            course_code = spans[0].get_text().strip()
            course_title = spans[1].get_text().strip()

            # Extract credits from hours span
            hours_span = title_block.find('span', class_='hours')
            credits = "N/A"
            if hours_span:
                hours_text = hours_span.get_text().strip()
                # Extract just the number part, e.g., "4.0 hours" -> "4.0"
                credits_match = re.search(r'([\d.]+(?:\s*-\s*[\d.]+)?)', hours_text)
                if credits_match:
                    credits = credits_match.group(1)

            # Parse course code into subject and number
            course_code_parts = course_code.split()
            if len(course_code_parts) < 2:
                return None

            subject = course_code_parts[0]
            course_number = ' '.join(course_code_parts[1:])

            # Extract core curriculum
            core_curriculum_elem = course_block.find('p', class_='core-curriculum')
            core_curriculum = "N/A"
            if core_curriculum_elem:
                label_span = core_curriculum_elem.find('span', class_='label')
                if label_span:
                    # Get text after the label
                    core_text = core_curriculum_elem.get_text().replace('Core Curriculum:', '').strip()
                    core_curriculum = core_text if core_text else "N/A"

            # Extract description
            description = "N/A"
            description_para = None
            for para in course_block.find_all('p', class_='noindent'):
                if 'core-curriculum' not in para.get('class', []) and 'prerequisite' not in para.get('class', []):
                    description_para = para
                    break

            if description_para:
                description = description_para.get_text().strip()

            # Extract prerequisites
            prerequisite_elem = course_block.find('p', class_='prerequisite')
            prerequisites = "N/A"
            prerequisite_courses = []

            if prerequisite_elem:
                # Get full prerequisite text
                prereq_text = prerequisite_elem.get_text().replace('Prerequisite:', '').strip()
                prerequisites = prereq_text if prereq_text else "N/A"

                # Extract prerequisite course codes from links
                prereq_links = prerequisite_elem.find_all('a', class_='bubblelink')
                for link in prereq_links:
                    title_attr = link.get('title', '')
                    if title_attr:
                        prerequisite_courses.append(title_attr.strip())

                # Also extract from text using regex
                text_courses = self.extract_prerequisite_courses(prerequisites)
                prerequisite_courses.extend(text_courses)

                # Remove duplicates
                prerequisite_courses = list(set(prerequisite_courses))

            # Build markdown content
            markdown_content = f"""# {course_code} - {course_title}

**Subject:** {subject}
**Course Number:** {course_number}
**Credits:** {credits}
**Level:** {level.title()}
**Core Curriculum:** {core_curriculum}

## Description

{description}

## Prerequisites

{prerequisites}

**Prerequisite Courses:** {', '.join(prerequisite_courses) if prerequisite_courses else 'None'}

**Source URL:** {subject_url}
"""

            # Create course URL (using subject URL + course code as unique identifier)
            course_url = f"{subject_url}#{course_code.replace(' ', '_')}"

            # Create metadata
            metadata = {
                'source': course_url,
                'content_hash': hashlib.sha256(markdown_content.encode('utf-8')).hexdigest(),
                'title': f"{course_code} - {course_title}",
                'course_code': course_code,
                'subject': subject,
                'course_number': course_number,
                'credits': credits,
                'level': level,
                'core_curriculum': core_curriculum,
                'prerequisites': prerequisites,
                'prerequisite_courses': prerequisite_courses,
                'description': description,
                'subject_url': subject_url
            }

            return Document(
                page_content=markdown_content,
                metadata=metadata
            )

        except Exception as e:
            logger.error(f"Error parsing course block: {e}")
            return None

    async def fetch_and_parse_course_page(self, session: aiohttp.ClientSession, url: str) -> List[Document]:
        """Fetch a course description page and parse all courses from it"""
        try:
            # Determine level from URL
            level = "undergraduate" if "/undergraduate/" in url else "graduate"

            headers = {
                'User-Agent': 'Mozilla/5.0 (compatible; Bradley University AI Assistant Crawler; +https://www.bradley.edu)',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            }

            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    logger.warning(f"Failed to fetch course page {url}: HTTP {response.status}")
                    return []

                html_content = await response.text()
                soup = BeautifulSoup(html_content, 'html.parser')

                # Find all course blocks
                course_blocks = soup.find_all('div', class_='courseblock')

                if not course_blocks:
                    logger.warning(f"No course blocks found on {url}")
                    return []

                courses = []
                for course_block in course_blocks:
                    course_doc = self.parse_course_block(course_block, url, level)
                    if course_doc:
                        courses.append(course_doc)

                logger.info(f"Parsed {len(courses)} courses from {url}")
                return courses

        except Exception as e:
            logger.error(f"Error fetching/parsing course page {url}: {e}")
            return []

    async def crawl_all_courses(self, force: bool = False) -> Dict[str, Any]:
        """Crawl all courses from the catalog. Unchanged courses are skipped unless force=True."""
        logger.info(f"Starting course catalog crawl (force={force})")
        stored = await asyncio.to_thread(self._stored_hashes)

        total_courses_stored = 0
        total_courses_unchanged = 0
        total_pages_processed = 0
        total_courses_found = 0

        async with aiohttp.ClientSession() as session:
            # Parse sitemap to get course description page URLs
            course_page_urls = await self.parse_catalog_sitemap(session)

            if not course_page_urls:
                logger.error("No course description pages found in sitemap")
                return {'error': 'No course description pages found'}

            logger.info(f"Processing {len(course_page_urls)} course description pages")

            # Process pages in batches
            batch_size = 5
            for i in range(0, len(course_page_urls), batch_size):
                batch_urls = course_page_urls[i:i + batch_size]
                batch_results = await asyncio.gather(
                    *(self.fetch_and_parse_course_page(session, url) for url in batch_urls), return_exceptions=True
                )

                changed = []
                for result in batch_results:
                    if isinstance(result, Exception):
                        logger.error(f"Error processing course page: {result}")
                        continue
                    for course_doc in result:
                        total_courses_found += 1
                        if not force and stored.get(course_doc.metadata['source']) == course_doc.metadata['content_hash']:
                            total_courses_unchanged += 1
                        else:
                            changed.append(course_doc)

                # One embedding pass per batch of pages, off the event loop
                total_courses_stored += await asyncio.to_thread(self.store_courses, changed)
                total_pages_processed += len(batch_urls)

                # Rate limiting between batches
                if i + batch_size < len(course_page_urls):
                    await asyncio.sleep(2.0)

        logger.info(f"Course crawl completed: {total_courses_stored} stored, {total_courses_unchanged} unchanged, "
                    f"{total_courses_found} found across {total_pages_processed} pages")

        return {
            'total_courses': await asyncio.to_thread(self.get_course_count),
            'total_courses_found': total_courses_found,
            'total_pages_processed': total_pages_processed,
            'courses_stored': total_courses_stored,
            'courses_unchanged': total_courses_unchanged,
            'timestamp': utc_iso()
        }

# Global crawler instance
course_crawler = CourseCatalogCrawler()

if __name__ == "__main__":
    import asyncio

    async def main():
        """Main function to run the course crawler"""
        logger.info("Starting Bradley University course catalog crawler...")

        try:
            # Run the crawler
            result = await course_crawler.crawl_all_courses(force=True)

            if 'error' in result:
                logger.error(f"Crawler failed: {result['error']}")
                return

            logger.info("Course crawler completed successfully!")
            logger.info(f"Results: {result}")

        except Exception as e:
            logger.error(f"Crawler error: {e}")
            import traceback
            traceback.print_exc()

    # Run the crawler
    asyncio.run(main())

