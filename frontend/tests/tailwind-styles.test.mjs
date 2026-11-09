import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import test from "node:test";
import postcss from "postcss";
import tailwind from "@tailwindcss/postcss";

test("the actual global stylesheet compiles layout and admin utilities instead of shipping raw Tailwind directives", async () => {
  const source = new URL("../app/globals.css", import.meta.url);
  const result = await postcss([tailwind({})]).process(readFileSync(source, "utf8"), { from: fileURLToPath(source) });
  assert.match(result.css, /\.flex\s*\{\s*display:\s*flex/);
  assert.match(result.css, /\.text-slate-900\s*\{/);
  assert.match(result.css, /\.rounded-xl\s*\{/);
  assert.doesNotMatch(result.css, /@(?:tailwind|theme)\s/);
});
