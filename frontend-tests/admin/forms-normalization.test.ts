import assert from "node:assert/strict";
import test from "node:test";

import { INVALID_JSON } from "../../gpt2giga/frontend/admin/forms-types.js";
import {
  parseOptionalJsonObject,
  parseOptionalNumber,
  trimToNull,
} from "../../gpt2giga/frontend/admin/forms-normalization.js";

test("trimToNull and parseOptionalNumber normalize blank and numeric field input", () => {
  assert.equal(trimToNull("  "), null);
  assert.equal(trimToNull(" demo "), "demo");

  assert.equal(parseOptionalNumber(""), null);
  assert.equal(parseOptionalNumber(" 12 "), 12);
  assert.equal(parseOptionalNumber("oops"), null);
});

test("parseOptionalJsonObject accepts plain objects and stringifies scalar values", () => {
  assert.deepEqual(
    parseOptionalJsonObject('{"authorization":"Bearer demo","retry":2,"enabled":true}'),
    {
      authorization: "Bearer demo",
      retry: "2",
      enabled: "true",
    },
  );
});

test("parseOptionalJsonObject rejects blank, invalid, and array payloads", () => {
  assert.equal(parseOptionalJsonObject("   "), null);
  assert.equal(parseOptionalJsonObject("{"), INVALID_JSON);
  assert.equal(parseOptionalJsonObject('["x"]'), INVALID_JSON);
});
