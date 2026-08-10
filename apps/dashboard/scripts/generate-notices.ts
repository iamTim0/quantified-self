/**
 * Collect the licence texts of everything the dashboard image ships.
 *
 * The image redistributes other people's code, and MIT, BSD-2-Clause and ISC all
 * require their copyright notice to travel with a copy. It used to satisfy that by
 * accident: the runtime stage shipped the full `node_modules`, which carries 271
 * licence files. Switching to Next's standalone output cut the image from 636 MB to
 * 155 MB by tracing only the JavaScript the server reaches — and traced none of
 * those files, so the notices silently stopped shipping.
 *
 * This puts them back deliberately, in one file, and adds the two the tree never
 * had: `next/font/google` self-hosts Outfit and JetBrains Mono, baking eleven
 * .woff2 files into the build, and both are OFL-1.1, which asks for its notice and
 * licence to accompany the font software. Their texts are vendored under
 * `licenses/` straight from the upstream projects rather than retyped.
 *
 *     bun run notices          # writes THIRD-PARTY-NOTICES.txt
 *     bun run notices --check  # fails if it would change; for CI
 *
 * Scope is the production dependency closure, walked from `dependencies`. Dev
 * tools — oxlint, typescript, Playwright — are not in the image and are not listed,
 * because a notice file that claims to describe the artefact should describe the
 * artefact.
 */

// A module, so the top-level `await`s below are legal under the app's tsconfig --
// `next build` type-checks this file along with the app, and a script that fails the
// type check fails the image build.
export {};

const LICENCE_FILENAMES = [
  "LICENSE",
  "LICENSE.md",
  "LICENSE.txt",
  "LICENCE",
  "LICENCE.md",
  "license",
  "license.md",
  "COPYING",
  "COPYING.md",
];

type Pkg = {
  name?: string;
  version?: string;
  license?: string | { type?: string };
  dependencies?: Record<string, string>;
};

async function readJson(path: string): Promise<Pkg | null> {
  try {
    return (await Bun.file(path).json()) as Pkg;
  } catch {
    return null;
  }
}

function licenceName(pkg: Pkg): string {
  if (typeof pkg.license === "string") return pkg.license;
  if (pkg.license && typeof pkg.license === "object" && pkg.license.type) return pkg.license.type;
  return "see below";
}

/**
 * Line endings normalised to LF, because the output has to be byte-identical on
 * every machine or `--check` becomes a coin flip.
 *
 * Some upstream licence files ship CRLF. Generating on Windows and committing
 * turned those into LF (git's autocrlf), while CI regenerated them as CRLF from the
 * same packages -- a 220-byte difference that read as "out of date" when nothing
 * was. Which line ending a notice uses is not part of the notice.
 */
function normalise(text: string): string {
  return text.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
}

async function findLicenceText(dir: string): Promise<string | null> {
  for (const name of LICENCE_FILENAMES) {
    const file = Bun.file(`${dir}/${name}`);
    if (await file.exists()) {
      const text = normalise(await file.text()).trim();
      if (text) return text;
    }
  }
  return null;
}

/** Production closure: every package reachable from `dependencies`, transitively. */
async function productionClosure(root: Pkg): Promise<string[]> {
  const seen = new Set<string>();
  const queue = Object.keys(root.dependencies ?? {});

  while (queue.length > 0) {
    const name = queue.shift()!;
    if (seen.has(name)) continue;
    const pkg = await readJson(`node_modules/${name}/package.json`);
    if (!pkg) continue; // an optional dependency for another platform
    seen.add(name);
    queue.push(...Object.keys(pkg.dependencies ?? {}));
  }

  return [...seen].sort();
}

const root = await readJson("package.json");
if (!root) {
  console.error("no package.json — run this from apps/dashboard");
  process.exit(2);
}

const packages = await productionClosure(root);

const sections: string[] = [];
const missing: string[] = [];

for (const name of packages) {
  const dir = `node_modules/${name}`;
  const pkg = (await readJson(`${dir}/package.json`))!;
  const text = await findLicenceText(dir);
  if (!text) missing.push(`${name} (${licenceName(pkg)})`);

  sections.push(
    [
      "-".repeat(78),
      `${name}@${pkg.version ?? "?"} — ${licenceName(pkg)}`,
      "-".repeat(78),
      "",
      text ?? `No licence file ships with this package. Declared licence: ${licenceName(pkg)}.`,
      "",
    ].join("\n"),
  );
}

// The fonts are not npm packages: next/font/google downloads them at build time and
// emits them into .next/static/media, so nothing in the dependency tree accounts
// for them.
for (const [label, file] of [
  ["Outfit (self-hosted webfont via next/font/google)", "licenses/Outfit-OFL.txt"],
  ["JetBrains Mono (self-hosted webfont via next/font/google)", "licenses/JetBrainsMono-OFL.txt"],
] as const) {
  const licence = Bun.file(file);
  if (!(await licence.exists())) {
    console.error(`missing vendored licence: ${file}`);
    process.exit(1);
  }
  sections.push(
    [
      "-".repeat(78),
      `${label} — OFL-1.1`,
      "-".repeat(78),
      "",
      normalise(await licence.text()).trim(),
      "",
    ].join("\n"),
  );
}

const output = [
  "THIRD-PARTY NOTICES",
  "",
  "The Quantified Self dashboard is licensed under AGPL-3.0-only; see LICENSE at the",
  "repository root. This file lists the third-party software redistributed inside the",
  "dashboard container image, with the licence text each one requires to be passed",
  "on. It is generated by scripts/generate-notices.ts from the production",
  "dependency closure — do not edit it by hand.",
  "",
  `${packages.length} packages, plus 2 self-hosted webfonts.`,
  "",
  ...sections,
].join("\n");

if (process.argv.includes("--check")) {
  const existing = Bun.file("THIRD-PARTY-NOTICES.txt");
  const current = (await existing.exists()) ? await existing.text() : "";
  if (current !== output) {
    console.error(
      "THIRD-PARTY-NOTICES.txt is out of date. Run `bun run notices` and commit the result.",
    );
    process.exit(1);
  }
  console.log(`THIRD-PARTY-NOTICES.txt is current (${packages.length} packages).`);
} else {
  await Bun.write("THIRD-PARTY-NOTICES.txt", output);
  console.log(`wrote THIRD-PARTY-NOTICES.txt: ${packages.length} packages + 2 webfonts`);
  if (missing.length > 0) {
    console.log(`no licence file found for ${missing.length}: ${missing.join(", ")}`);
  }
}
