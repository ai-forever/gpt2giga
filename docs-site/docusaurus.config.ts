import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

const config: Config = {
  title: 'gpt2giga and GigaLoom',
  tagline: 'FastAPI gateway from OpenAI, Anthropic and Gemini clients to GigaChat',
  favicon: 'brand/gigaloom-mark.svg',

  future: {
    v4: true,
  },

  url: 'https://krakenalt.github.io',
  baseUrl: '/gigaloom/',
  organizationName: 'krakenalt',
  projectName: 'gigaloom',

  onBrokenLinks: 'throw',
  markdown: {
    mermaid: true,
    hooks: {
      onBrokenMarkdownLinks: 'throw',
    },
  },

  themes: ['@docusaurus/theme-mermaid'],

  plugins: [
    [
      '@cmfcmf/docusaurus-search-local',
      {
        indexDocs: true,
        indexDocSidebarParentCategories: 2,
        includeParentCategoriesInPageTitle: true,
        indexBlog: false,
        indexPages: false,
        language: ['en', 'ru'],
        maxSearchResults: 10,
      },
    ],
  ],

  i18n: {
    defaultLocale: 'en',
    locales: ['en', 'ru'],
    localeConfigs: {
      en: {label: 'English', htmlLang: 'en'},
      ru: {label: 'Русский', htmlLang: 'ru'},
    },
  },

  presets: [
    [
      'classic',
      {
        docs: {
          path: '../docs',
          routeBasePath: '/',
          sidebarPath: './sidebars.ts',
          editUrl: 'https://github.com/ai-forever/gpt2giga/edit/main/docs/',
          exclude: ['internal/**', 'codex/**'],
        },
        blog: false,
        pages: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],

  themeConfig: {
    colorMode: {
      respectPrefersColorScheme: true,
    },
    navbar: {
      title: 'gpt2giga · GigaLoom',
      logo: {
        alt: 'GigaLoom',
        src: 'brand/gigaloom-mark.svg',
        srcDark: 'brand/gigaloom-mark-dark.svg',
      },
      items: [
        {
          type: 'docSidebar',
          sidebarId: 'docs',
          position: 'left',
          label: 'Documentation',
        },
        {to: '/quickstart', label: 'Quickstart', position: 'left'},
        {to: '/harness', label: 'Harness', position: 'left'},
        {to: '/agent-capability-matrix', label: 'Capabilities', position: 'left'},
        {type: 'localeDropdown', position: 'right'},
        {
          href: 'https://github.com/ai-forever/gpt2giga',
          label: 'GitHub',
          position: 'right',
        },
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: 'Documentation',
          items: [
            {label: 'Overview', to: '/'},
            {label: 'Quickstart', to: '/quickstart'},
            {label: 'Harness', to: '/harness'},
          ],
        },
        {
          title: 'Architecture',
          items: [
            {label: 'Harness architecture', to: '/architecture/harness'},
            {label: 'Capability matrix', to: '/agent-capability-matrix'},
            {label: 'Contributing', to: '/contributing'},
          ],
        },
        {
          title: 'Project',
          items: [
            {label: 'GitHub', href: 'https://github.com/ai-forever/gpt2giga'},
            {label: 'Examples', href: 'https://github.com/ai-forever/gpt2giga/tree/main/examples'},
          ],
        },
      ],
      copyright: `© ${new Date().getFullYear()} gpt2giga contributors. Built with Docusaurus.`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
