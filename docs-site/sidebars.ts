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
          label: '0.3 universal bridge ADRs',
          collapsible: true,
          collapsed: true,
          items: [
            'architecture/2026-08-03-normalized-responses-execution-adr',
            'architecture/2026-08-03-provider-profiles-model-aliases-adr',
            'architecture/2026-08-03-bridge-status-loss-matrix-adr',
            'architecture/2026-08-03-supervisor-machine-contract-adr',
            'architecture/2026-08-03-provider-security-boundary-adr',
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
          id: 'gigaloom-migration',
          label: 'GigaLoom migration',
        },
      ],
    },
  ],
};

export default sidebars;
