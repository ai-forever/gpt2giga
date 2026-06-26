import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

const config: Config = {
  title: 'gpt2giga',
  tagline: 'FastAPI gateway from OpenAI, Anthropic and Gemini clients to GigaChat',

  future: {
    v4: true,
  },

  url: 'https://ai-forever.github.io',
  baseUrl: '/gpt2giga/',
  organizationName: 'ai-forever',
  projectName: 'gpt2giga',

  onBrokenLinks: 'throw',
  markdown: {
    hooks: {
      onBrokenMarkdownLinks: 'warn',
    },
  },

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
      title: 'gpt2giga',
      items: [
        {
          type: 'docSidebar',
          sidebarId: 'docs',
          position: 'left',
          label: 'Documentation',
        },
        {to: '/quickstart', label: 'Quickstart', position: 'left'},
        {to: '/api-compatibility', label: 'Compatibility', position: 'left'},
        {to: '/operations', label: 'Operations', position: 'left'},
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
            {label: 'Configuration', to: '/configuration'},
          ],
        },
        {
          title: 'Compatibility',
          items: [
            {label: 'API compatibility', to: '/api-compatibility'},
            {label: 'Client parameters', to: '/client-parameter-compatibility'},
            {label: 'Built-in tools', to: '/builtin-tools'},
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
