/**
 * The installable app's icons, rendered from one vector source.
 *
 * Run with `bun run icons`. The PNGs are committed, because a manifest that
 * points at files produced only by a local script is a manifest that breaks the
 * moment anyone builds without running it.
 *
 * Two shapes, not one. A `purpose: "any"` icon is drawn as-is and keeps its own
 * rounded square; a `purpose: "maskable"` icon is cropped by the platform to
 * whatever silhouette it likes — a circle on Android, a squircle on iOS — so it
 * has to bleed its background to the edges and keep the glyph inside the inner
 * 80% safe zone. Shipping the first as the second is what produces an app icon
 * with its corners sliced off.
 *
 * The mark is the one the sidebar already uses: Lucide's `Activity` on the brand
 * green, so the installed app and the running app agree about what they are.
 */

import sharp from "sharp";
import { mkdir } from "node:fs/promises";

/** `--primary` from `globals.css`, light theme. */
const BRAND = "#0d5c3a";
const GLYPH = "#ffffff";

/** Lucide `Activity`, on its native 24×24 grid. */
const ACTIVITY_PATH = "M22 12h-4l-3 9L9 3l-3 9H2";

/**
 * @param size    Output edge length in pixels.
 * @param bleed   `true` for maskable: fill the whole canvas and shrink the glyph
 *                into the safe zone. `false` keeps the app's own rounded square.
 */
function iconSvg(size: number, bleed: boolean): string {
  // The glyph occupies 55% of the canvas when maskable (comfortably inside the
  // 80% safe circle) and 62% otherwise.
  const glyphScale = bleed ? 0.55 : 0.62;
  const glyphSize = size * glyphScale;
  const offset = (size - glyphSize) / 2;
  const scale = glyphSize / 24;
  const radius = bleed ? 0 : size * 0.22;
  const strokeWidth = 2.25 / scale;

  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
  <rect width="${size}" height="${size}" rx="${radius}" ry="${radius}" fill="${BRAND}"/>
  <g transform="translate(${offset} ${offset}) scale(${scale})">
    <path d="${ACTIVITY_PATH}" fill="none" stroke="${GLYPH}" stroke-width="${strokeWidth}"
          stroke-linecap="round" stroke-linejoin="round"/>
  </g>
</svg>`;
}

const OUT = new URL("../public/icons/", import.meta.url);

const TARGETS = [
  { file: "icon-192.png", size: 192, bleed: false },
  { file: "icon-512.png", size: 512, bleed: false },
  { file: "icon-maskable-192.png", size: 192, bleed: true },
  { file: "icon-maskable-512.png", size: 512, bleed: true },
  // Apple ignores the manifest and reads `apple-touch-icon`. It also composites
  // onto white if the PNG has alpha, so this one is opaque and unrounded — iOS
  // applies its own squircle.
  { file: "apple-touch-icon.png", size: 180, bleed: true },
] as const;

await mkdir(OUT, { recursive: true });

for (const { file, size, bleed } of TARGETS) {
  const svg = iconSvg(size, bleed);
  await sharp(Buffer.from(svg)).png().toFile(new URL(file, OUT).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
  console.log(`wrote ${file} (${size}px${bleed ? ", maskable" : ""})`);
}

// The vector, for anything that prefers it — and as the editable source.
await Bun.write(new URL("icon.svg", OUT), iconSvg(512, false));
console.log("wrote icon.svg");
