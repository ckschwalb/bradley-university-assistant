import js from '@eslint/js';
import globals from 'globals';
import react from 'eslint-plugin-react';
import reactHooks from 'eslint-plugin-react-hooks';

export default [
  { ignores: ['build/', 'node_modules/'] },
  js.configs.recommended,
  react.configs.flat.recommended,
  react.configs.flat['jsx-runtime'],
  {
    files: ['**/*.{js,jsx}'],
    plugins: { 'react-hooks': reactHooks },
    languageOptions: { globals: { ...globals.browser } },
    settings: { react: { version: 'detect' } },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react/prop-types': 'off', // the components are internal and untyped by design
      'react/no-unescaped-entities': ['error', { forbid: ['>', '"', '}'] }], // apostrophes in text are fine
      // `import React` is still written in each file though the JSX runtime no longer needs it
      'no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^(_|React$)', ignoreRestSiblings: true }],
    },
  },
  {
    // Tests and config run under Node and vitest
    files: ['**/__tests__/**', 'src/setupTests.js', 'vite.config.js', 'eslint.config.js'],
    languageOptions: { globals: { ...globals.node, ...globals.vitest } },
  },
];
