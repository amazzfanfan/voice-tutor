import '@testing-library/jest-dom';

// react-markdown v10 is ESM-only, while react-scripts 5 runs Jest in a
// CommonJS environment. Keep component tests focused on the integration
// contract (AI text is passed to the Markdown renderer); production rendering
// is covered by the webpack build and browser-level checks.
jest.mock('react-markdown', () => {
  const React = require('react');
  return function MarkdownTestDouble({ children }) {
    return React.createElement(
      'div',
      { 'data-testid': 'markdown-output', 'data-markdown-source': children },
      children
    );
  };
});

jest.mock('remark-gfm', () => () => null);
