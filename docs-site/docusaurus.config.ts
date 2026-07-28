import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

const config: Config = {
  title: 'GigaLoom',
  tagline: 'Local, provider-neutral control plane for coding agents',
  favicon: 'brand/gigaloom-mark.svg',

  future: {
    v4: true,
  },

  url: 'https://krakenalt.github.io',
  baseUrl: '/gigaloom/',
  organizationName: 'krakenalt',
  projectName: 'gigaloom',
  trailingSlash: false,

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
          editUrl: ({locale, docPath}) =>
            locale === 'ru'
              ? `https://github.com/krakenalt/gigaloom/edit/main/docs-site/i18n/ru/docusaurus-plugin-content-docs/current/${docPath}`
              : `https://github.com/krakenalt/gigaloom/edit/main/docs/${docPath}`,
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
      title: 'GigaLoom',
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
        {to: '/architecture', label: 'Architecture', position: 'left'},
        {to: '/agent-capability-matrix', label: 'Capabilities', position: 'left'},
        {type: 'localeDropdown', position: 'right'},
        {
          href: 'https://github.com/krakenalt/gigaloom',
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
            {label: 'Installation', to: '/installation'},
            {label: 'Quickstart', to: '/quickstart'},
            {label: 'Operations', to: '/operations'},
          ],
        },
        {
          title: 'Architecture',
          items: [
            {label: 'Architecture', to: '/architecture'},
            {label: 'Security', to: '/security'},
            {label: 'Gateway integration', to: '/gateway-integration'},
            {label: 'Capability matrix', to: '/agent-capability-matrix'},
          ],
        },
        {
          title: 'Project',
          items: [
            {label: 'GitHub', href: 'https://github.com/krakenalt/gigaloom'},
            {label: 'Contributing', to: '/contributing'},
            {label: 'Release', to: '/release'},
            {label: 'Source history', to: '/source-history'},
          ],
        },
      ],
      copyright: `© ${new Date().getFullYear()} GigaLoom contributors. Built with Docusaurus.`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
