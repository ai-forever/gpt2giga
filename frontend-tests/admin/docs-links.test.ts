import assert from "node:assert/strict";
import test from "node:test";

import {
  API_COMPATIBILITY_URL,
  CANONICAL_DOC_LINKS,
  CONFIGURATION_GUIDE_URL,
  DOCS_INDEX_URL,
  OPERATOR_GUIDE_LINKS,
  UPGRADE_GUIDE_URL,
} from "../../gpt2giga/frontend/admin/docs-links.js";

test("docs links only expose canonical docs pages", () => {
  assert.equal(DOCS_INDEX_URL, "https://github.com/ai-forever/gpt2giga/blob/main/docs/README.md");
  assert.equal(
    CONFIGURATION_GUIDE_URL,
    "https://github.com/ai-forever/gpt2giga/blob/main/docs/configuration.md",
  );
  assert.equal(
    API_COMPATIBILITY_URL,
    "https://github.com/ai-forever/gpt2giga/blob/main/docs/api-compatibility.md",
  );
  assert.equal(
    UPGRADE_GUIDE_URL,
    "https://github.com/ai-forever/gpt2giga/blob/main/docs/upgrade-0.x-to-1.0.md",
  );
  assert.equal(
    OPERATOR_GUIDE_LINKS.providers,
    "https://github.com/ai-forever/gpt2giga/blob/main/docs/operator-guide.md#provider-surface-diagnostics",
  );
  assert.equal(CANONICAL_DOC_LINKS.index, DOCS_INDEX_URL);
  assert.equal(CANONICAL_DOC_LINKS.configuration, CONFIGURATION_GUIDE_URL);
  assert.equal(CANONICAL_DOC_LINKS.compatibility, API_COMPATIBILITY_URL);
  assert.equal(CANONICAL_DOC_LINKS.upgrade, UPGRADE_GUIDE_URL);

  for (const href of [
    ...Object.values(CANONICAL_DOC_LINKS),
    ...Object.values(OPERATOR_GUIDE_LINKS),
  ]) {
    assert.match(href, /\/docs\//);
    assert.doesNotMatch(href, /\/docs\/internal\//);
  }
});
