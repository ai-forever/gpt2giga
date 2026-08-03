import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

const sidebars: SidebarsConfig = {
  docs: [
    {
      type: 'category',
      label: 'Overview',
      collapsible: false,
      items: ['index', 'quickstart', 'configuration', 'provider-profiles'],
    },
    {
      type: 'category',
      label: 'Compatibility',
      collapsible: false,
      items: [
        'api-compatibility',
        'bridge-compatibility',
        'client-parameter-compatibility',
        'builtin-tools',
        'integrations',
      ],
    },
    {
      type: 'category',
      label: 'Operations',
      collapsible: false,
      items: ['deployment', 'operations', 'live-integration-tests'],
    },
    {
      type: 'category',
      label: 'Architecture',
      collapsible: false,
      items: [
        'architecture/normalized-messages',
        'architecture/logging-and-observability',
        'architecture/how-to-add-provider',
        {
          type: 'category',
          label: 'gpt2giga 0.3',
          collapsible: true,
          collapsed: true,
          items: [
            'architecture/responses-execution',
            'architecture/provider-routing',
            'architecture/bridge-compatibility-matrix',
            'architecture/supervisor-api',
            'architecture/provider-security',
          ],
        },
      ],
    },
    {
      type: 'category',
      label: 'Contributing',
      collapsible: false,
      items: ['contributing'],
    },
    {
      type: 'category',
      label: 'Migration and legacy',
      collapsible: true,
      collapsed: true,
      items: [
        {
          type: 'doc',
          id: 'migration-0-3',
        },
        {
          type: 'doc',
          id: 'gigaloom-migration',
        },
      ],
    },
  ],
};

export default sidebars;
