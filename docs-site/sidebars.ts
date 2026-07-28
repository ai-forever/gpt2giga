import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

const sidebars: SidebarsConfig = {
  docs: [
    {
      type: 'category',
      label: 'Overview',
      collapsible: false,
      items: [
        'index',
        'installation',
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
        'agent-capability-matrix',
      ],
    },
    {
      type: 'category',
      label: 'Operate',
      collapsible: false,
      items: ['operations', 'security', 'gateway-integration'],
    },
    {
      type: 'category',
      label: 'Architecture',
      collapsible: false,
      items: [
        'architecture',
        'architecture/harness',
        'architecture/product-capability-admission-adr',
        'architecture/authority-approval-schema-adr',
        'architecture/scoped-network-access-adr',
        'architecture/github-capability-grants-adr',
        'architecture/provider-authentication-capability-matrix',
        'architecture/remote-ui-identity-adr',
        'architecture/frontend-asset-build-architecture-adr',
        'architecture/provider-native-cli-facade-adr',
      ],
    },
    {
      type: 'category',
      label: 'Project',
      collapsible: false,
      items: ['contributing', 'release', 'source-history'],
    },
  ],
};

export default sidebars;
