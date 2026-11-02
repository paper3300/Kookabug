// Playwright 스크린샷(PNG) 픽셀 읽기: 8비트 RGB·RGBA, 비월 없음만 (Chromium 스크린샷 형식). 영상 칸 색 확인용
// (kbimg 영상은 app:// 와 출처가 달라 캔버스로 읽으면 오염된다)
import zlib from "node:zlib";

export interface Png {
  width: number;
  height: number;
  /** 한 픽셀 바이트 수 (3 또는 4) */
  channels: number;
  data: Buffer;
}

export function decodePng(buf: Buffer): Png {
  if (buf.readUInt32BE(0) !== 0x89504e47) throw new Error("PNG가 아니다");
  let off = 8;
  let width = 0;
  let height = 0;
  let channels = 0;
  const idat: Buffer[] = [];
  while (off < buf.length) {
    const len = buf.readUInt32BE(off);
    const type = buf.toString("ascii", off + 4, off + 8);
    const body = buf.subarray(off + 8, off + 8 + len);
    if (type === "IHDR") {
      width = body.readUInt32BE(0);
      height = body.readUInt32BE(4);
      const depth = body[8];
      const color = body[9];
      if (depth !== 8 || (color !== 2 && color !== 6) || body[12] !== 0) throw new Error(`읽을 수 없는 PNG 형식 (${depth}, ${color})`);
      channels = color === 6 ? 4 : 3;
    } else if (type === "IDAT") {
      idat.push(body);
    } else if (type === "IEND") {
      break;
    }
    off += 12 + len;
  }
  const raw = zlib.inflateSync(Buffer.concat(idat));
  const stride = width * channels;
  const data = Buffer.alloc(stride * height);
  for (let y = 0; y < height; y++) {
    const filter = raw[y * (stride + 1)];
    const line = raw.subarray(y * (stride + 1) + 1, (y + 1) * (stride + 1));
    for (let x = 0; x < stride; x++) {
      const a = x >= channels ? data[y * stride + x - channels] : 0;
      const b = y > 0 ? data[(y - 1) * stride + x] : 0;
      const c = x >= channels && y > 0 ? data[(y - 1) * stride + x - channels] : 0;
      let v = line[x];
      if (filter === 1) v += a;
      else if (filter === 2) v += b;
      else if (filter === 3) v += (a + b) >> 1;
      else if (filter === 4) {
        const p = a + b - c;
        const pa = Math.abs(p - a);
        const pb = Math.abs(p - b);
        const pc = Math.abs(p - c);
        v += pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
      }
      data[y * stride + x] = v & 0xff;
    }
  }
  return { width, height, channels, data };
}

/** (x, y) 픽셀 [r, g, b] */
export function pixel(png: Png, x: number, y: number): [number, number, number] {
  const i = (Math.floor(y) * png.width + Math.floor(x)) * png.channels;
  return [png.data[i], png.data[i + 1], png.data[i + 2]];
}

/** 가장 센 채널: "red" | "green" | "blue" (영상 표본 칸 색) */
export function dominant([r, g, b]: [number, number, number]): "red" | "green" | "blue" {
  if (r >= g && r >= b) return "red";
  return g >= b ? "green" : "blue";
}
