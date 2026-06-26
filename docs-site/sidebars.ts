import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

const sidebars: SidebarsConfig = {
  docs: [
    {
      type: 'category',
      label: 'Overview',
      collapsible: false,
      items: ['index', 'quickstart', 'configuration'],
    },
    {
      type: 'category',
      label: 'Compatibility',
      collapsible: false,
      items: [
        'api-compatibility',
        'client-parameter-compatibility',
        'diagnostics',
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
      ],
    },
    {
      type: 'category',
      label: 'Contributing',
      collapsible: false,
      items: ['contributing'],
    },
  ],
};

export default sidebars;
