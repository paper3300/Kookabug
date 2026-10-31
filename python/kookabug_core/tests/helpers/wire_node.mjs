// 검사 도우미: stdin의 JSON 텍스트 배열을 JS 값으로 읽고 전송 코덱(또는 JSON.stringify)으로 다시 쓴다.
//   node wire_node.mjs <wire|json> <packages/schema/src/wire.ts 경로>
// wire.ts는 Node 타입 제거 실행으로 그대로 불러온다 (번들 없이 실제 코덱 코드)
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const [mode, wirePath] = process.argv.slice(2);
const { wireStringify } = await import(pathToFileURL(wirePath).href);
const texts = JSON.parse(readFileSync(0, "utf8"));
const out = texts.map((text) => {
  const value = JSON.parse(text);
  try {
    return { ok: mode === "wire" ? wireStringify(value) : JSON.stringify(value) };
  } catch (e) {
    return { error: `${e.name}: ${e.message}`, pointer: e.pointer ?? null };
  }
});
// 짝 없는 대리 문자는 JSON.stringify가 이스케이프한다 (stdout은 ASCII가 아니어도 UTF-8로 안전)
process.stdout.write(JSON.stringify(out));
