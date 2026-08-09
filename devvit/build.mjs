// Bundles the server into the single self-contained CommonJS file Devvit expects
// at dist/server/index.js. Run by `devvit upload` and `devvit playtest` via the
// `scripts` block in devvit.json.
//
// The corpus is imported as JSON and therefore inlined into the bundle — the
// server entry has no filesystem to read from at runtime.

import { build, context } from 'esbuild';
import { existsSync } from 'node:fs';

const CORPUS = 'src/server/corpus.generated.json';

if (!existsSync(CORPUS)) {
  console.error(
    `\nMissing ${CORPUS}.\n` +
      `Build the corpus first, from the repo root:\n\n` +
      `  python scripts/build_corpus.py\n` +
      `  python scripts/export_corpus_json.py\n`
  );
  process.exit(1);
}

/** @type {import('esbuild').BuildOptions} */
const options = {
  entryPoints: ['src/server/index.ts'],
  outfile: 'dist/server/index.js',
  bundle: true,
  platform: 'node',
  target: 'node22',
  format: 'cjs',
  sourcemap: false,
  minify: true,
  // Node built-ins stay external; everything else is inlined.
  external: ['node:*'],
  logLevel: 'info',
};

if (process.argv.includes('--watch')) {
  const ctx = await context(options);
  await ctx.watch();
  console.log('watching...');
} else {
  await build(options);
}
