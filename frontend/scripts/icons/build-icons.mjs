// Regenerates every raster app icon from the two SVG masters, so a change to
// the design is one edit plus `npm run icons` (run from frontend/).
//
//   app/icon.svg              → app/favicon.ico (16, 32, 48)
//                             → public/icons/icon-192.png, icon-512.png
//   scripts/icons/fullbleed.svg → app/apple-icon.png (180)
//                             → public/icons/maskable-512.png
//
// Rendering uses the Chromium Playwright already installed for the e2e tests.

import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const tile = readFileSync(join(root, "app", "icon.svg"));
const fullBleed = readFileSync(join(root, "scripts", "icons", "fullbleed.svg"));

async function render(page, svg, size) {
  await page.setViewportSize({ width: size, height: size });
  await page.setContent(
    `<style>html,body{margin:0;background:transparent}</style>` +
      `<img src="data:image/svg+xml;base64,${svg.toString("base64")}" ` +
      `width="${size}" height="${size}" style="display:block">`,
  );
  await page.waitForFunction(() => document.images[0]?.complete);
  return page.screenshot({ omitBackground: true, type: "png" });
}

/** An .ico holding PNG images — the format every current browser reads. */
function packIco(images) {
  const header = Buffer.alloc(6);
  header.writeUInt16LE(0, 0); // reserved
  header.writeUInt16LE(1, 2); // type: icon
  header.writeUInt16LE(images.length, 4);

  let offset = header.length + 16 * images.length;
  const entries = images.map(({ size, data }) => {
    const entry = Buffer.alloc(16);
    entry.writeUInt8(size >= 256 ? 0 : size, 0); // width (0 means 256)
    entry.writeUInt8(size >= 256 ? 0 : size, 1); // height
    entry.writeUInt16LE(1, 4); // colour planes
    entry.writeUInt16LE(32, 6); // bits per pixel
    entry.writeUInt32LE(data.length, 8);
    entry.writeUInt32LE(offset, 12);
    offset += data.length;
    return entry;
  });
  return Buffer.concat([header, ...entries, ...images.map((image) => image.data)]);
}

const browser = await chromium.launch();
const page = await browser.newPage({ deviceScaleFactor: 1 });

const favicon = [];
for (const size of [16, 32, 48]) {
  favicon.push({ size, data: await render(page, tile, size) });
}

mkdirSync(join(root, "public", "icons"), { recursive: true });
const outputs = {
  "app/favicon.ico": packIco(favicon),
  "app/apple-icon.png": await render(page, fullBleed, 180),
  "public/icons/icon-192.png": await render(page, tile, 192),
  "public/icons/icon-512.png": await render(page, tile, 512),
  "public/icons/maskable-512.png": await render(page, fullBleed, 512),
};
await browser.close();

for (const [path, data] of Object.entries(outputs)) {
  writeFileSync(join(root, path), data);
  console.log(`${path.padEnd(32)} ${(data.length / 1024).toFixed(1)} KB`);
}
