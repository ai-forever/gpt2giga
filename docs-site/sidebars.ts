import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

const sidebars: SidebarsConfig = {
  docs: [
    {
      type: 'category',
      label: 'Overview',
      collapsible: false,
      items: [
        'index',
        'quickstart',
        {
          type: 'doc',
          id: 'harness',
          label: 'Unified Harness (alpha)',
          key: 'harness',
        },
        {
          type: 'doc',
          id: 'agents-and-multi-agent',
          label: 'Agents and multi-agent behavior',
          key: 'agents-and-multi-agent',
        },
        'configuration',
      ],
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
        'architecture/harness',
        'architecture/product-capability-admission-adr',
        'architecture/authority-approval-schema-adr',
        'architecture/scoped-network-access-adr',
        'architecture/github-capability-grants-adr',
        'architecture/provider-authentication-capability-matrix',
        'architecture/remote-ui-identity-adr',
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
