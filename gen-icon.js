/**
 * Writes icon.png — the reactor core, drawn in code so the repo carries no
 * binary asset. Run with: node gen-icon.js
 */
const fs = require("fs");
const zlib = require("zlib");

const SIZE = 256;

function draw(size) {
  const px = Buffer.alloc(size * size * 4);
  const c = (size - 1) / 2;
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const d = Math.hypot(x - c, y - c) / c;
      const i = (y * size + x) * 4;
      if (d > 1) continue;
      const core = Math.max(0, 1 - d * 2.6);
      const ring = d > 0.74 && d < 0.94 ? 1 : 0;
      const halo = Math.max(0, 0.5 - d * 0.5);
      const a = Math.min(1, core + ring * 0.95 + halo);
      px[i]     = Math.round(30 + 215 * core);
      px[i + 1] = Math.round(180 + 75 * core);
      px[i + 2] = 255;
      px[i + 3] = Math.round(a * 255);
    }
  }
  return px;
}

function png(size, px) {
  const raw = Buffer.alloc((size * 4 + 1) * size);
  for (let y = 0; y < size; y++) {
    raw[y * (size * 4 + 1)] = 0;
    px.copy(raw, y * (size * 4 + 1) + 1, y * size * 4, (y + 1) * size * 4);
  }
  const table = [];
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  const crc = (buf) => {
    let c = 0xffffffff;
    for (const b of buf) c = table[(c ^ b) & 0xff] ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
  };
  const chunk = (type, data) => {
    const len = Buffer.alloc(4); len.writeUInt32BE(data.length);
    const td = Buffer.concat([Buffer.from(type, "ascii"), data]);
    const cr = Buffer.alloc(4); cr.writeUInt32BE(crc(td));
    return Buffer.concat([len, td, cr]);
  };
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0); ihdr.writeUInt32BE(size, 4);
  ihdr[8] = 8; ihdr[9] = 6;
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", ihdr),
    chunk("IDAT", zlib.deflateSync(raw, { level: 9 })),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

fs.writeFileSync("icon.png", png(SIZE, draw(SIZE)));
console.log(`icon.png written (${SIZE}x${SIZE})`);
