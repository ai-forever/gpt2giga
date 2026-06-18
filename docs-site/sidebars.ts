import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

const sidebars: SidebarsConfig = {
  docs: [
    {
      type: 'category',
      label: 'Обзор',
      collapsible: false,
      items: ['index', 'quickstart', 'configuration'],
    },
    {
      type: 'category',
      label: 'Совместимость',
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
      label: 'Эксплуатация',
      collapsible: false,
      items: ['deployment', 'operations', 'live-integration-tests'],
    },
    {
      type: 'category',
      label: 'Архитектура',
      collapsible: false,
      items: [
        'architecture/normalized-messages',
        'architecture/logging-and-observability',
        'architecture/how-to-add-provider',
      ],
    },
    {
      type: 'category',
      label: 'Участие',
      collapsible: false,
      items: ['contributing'],
    },
  ],
};

export default sidebars;
