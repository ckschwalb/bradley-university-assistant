import { formatWhen, plural } from './api';

// When the crawler service will start the next scheduled crawl (see due_trigger in crawler_service.py)
export const nextCrawlAt = (crawl) => {
  if (!crawl || !crawl.auto_crawl || !crawl.auto_crawl.enabled || !crawl.finished_at) return null;
  return new Date(new Date(crawl.finished_at).getTime() + crawl.auto_crawl.interval_hours * 3600 * 1000);
};

export const indexedItems = (crawl) => (crawl ? crawl.document_count + crawl.course_count : 0);

// {tone, label} for the index as a whole
export const crawlState = (crawl) => {
  if (!crawl) return { tone: 'plain', label: 'Loading' };
  if (crawl.status === 'running') {
    return { tone: 'plain', label: crawl.progress === 'courses' ? 'Crawling the course catalog' : 'Crawling the website' };
  }
  if (crawl.requested_at) return { tone: 'plain', label: 'Starting soon' };
  if (!crawl.crawler_online) return { tone: 'bad', label: 'Crawler offline' };
  if (crawl.error) return { tone: 'bad', label: 'Last crawl failed' };
  if (indexedItems(crawl) === 0) return { tone: 'warn', label: 'Not indexed yet' };
  return { tone: 'good', label: 'Up to date' };
};

// One sentence about the last crawl's outcome
export const lastCrawlSummary = (crawl) => {
  if (!crawl || !crawl.finished_at) return 'No crawl has finished yet.';
  const parts = [];
  const site = crawl.last_result && crawl.last_result.site;
  const courses = crawl.last_result && crawl.last_result.courses;
  if (site) {
    parts.push(site.error
      ? `the website failed (${site.error})`
      : `checked ${plural(site.items_listed, 'website item')}: ${site.documents_stored} updated, ${site.documents_deleted} removed`);
  }
  if (courses) {
    parts.push(courses.error
      ? `the course catalog failed (${courses.error})`
      : `${plural(courses.courses_stored, 'course')} updated, ${courses.courses_unchanged.toLocaleString('en-US')} unchanged`);
  }
  return `Last crawl ${formatWhen(crawl.finished_at)}${parts.length ? `: ${parts.join('; ')}` : ''}.`;
};
