import '@testing-library/jest-dom/vitest';

// Times show in the viewer's zone; pin one so the tests read the same everywhere
process.env.TZ = 'America/Chicago';

// jsdom has no layout and doesn't implement element scrolling
Element.prototype.scrollTo = Element.prototype.scrollTo || function scrollTo() {};
