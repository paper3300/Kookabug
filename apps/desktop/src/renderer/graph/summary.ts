// 노드 설명 줄 = 주요 입력 요약 (M2 계획 T8, 시안 Main의 '"강화" · 유사도 0.93', 'title = SampleRPG*').
// 연결($link)은 연결선으로 보이므로 쓰지 않는다
import { findLinks, isObject, own, specialTag, type GraphNodeValue } from "./model";

const MAX_PARTS = 3;
const MAX_TEXT = 24;

function clip(s: string, max = MAX_TEXT): string {
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}

/** 경로의 파일 이름에서 종류 꼬리(.target.json·.graph.json)를 뗀다 */
export function stem(path: string): string {
  const name = path.split("/").pop() ?? path;
  return name.replace(/\.(target|graph|screen)\.json$/, "").replace(/\.json$/, "");
}

/** 핀 줄에 이름과 함께 쓸 짧은 상수 (수·참거짓·짧은 글자). 아니면 null */
export function shortConstant(v: unknown): string | null {
  if (typeof v === "number") return String(v);
  if (typeof v === "boolean") return v ? "켬" : "끔";
  if (typeof v === "string" && v.length <= 12) return JSON.stringify(v);
  return null;
}

function describe(name: string, v: unknown): string | null {
  const tag = specialTag(v);
  if (tag !== null) {
    const inner = own(v, tag);
    switch (tag) {
      case "$link":
        return null;
      case "$target":
        return typeof inner === "string" ? `"${clip(stem(inner))}"` : null;
      case "$setting":
        return typeof inner === "string" ? `${name} = 설정 ${clip(inner)}` : null;
      case "$secret":
        return typeof inner === "string" ? `${name} = 비밀 ${clip(inner)}` : null;
      case "$literal":
        return `${name} = 그대로 넣은 값`;
      default:
        return null;
    }
  }
  if (v === null || v === undefined) return null;
  if (typeof v === "string") return `${name} = ${clip(v)}`;
  if (typeof v === "number") return `${name} ${v}`;
  if (typeof v === "boolean") return `${name} ${v ? "켬" : "끔"}`;
  // 연결만 든 목록·사전은 연결선으로 보인다
  if (findLinks(v).length > 0 && Array.isArray(v) && v.every((x) => specialTag(x) === "$link")) return null;
  if (Array.isArray(v)) return `${name} [${v.length}]`;
  if (isObject(v)) {
    const targets = Object.values(v).filter((x) => specialTag(x) === "$target");
    if (targets.length > 0 && targets.length === Object.keys(v).length) {
      return Object.keys(v)
        .map((k) => clip(k, 12))
        .join(" / ");
    }
    return `${name} {${Object.keys(v).length}}`;
  }
  return null;
}

function configSummary(node: GraphNodeValue): string[] {
  const out: string[] = [];
  const graph = own(node.config, "graph");
  if (typeof graph === "string") out.push(`→ ${clip(stem(graph))}`);
  const exit = own(node.config, "exit");
  if (typeof exit === "string") out.push(`출구 ${clip(exit)}`);
  return out;
}

/** 설명 줄. skip = 핀 줄에 이미 값을 쓴 핀. order = 노드 스키마 핀 순서(없는 키는 뒤에 파일 순서) */
export function summarize(node: GraphNodeValue, order: readonly string[], skip: ReadonlySet<string>): string | null {
  const keys = [...order.filter((k) => Object.hasOwn(node.in, k)), ...Object.keys(node.in).filter((k) => !order.includes(k))];
  const parts = [...configSummary(node)];
  for (const k of keys) {
    if (skip.has(k)) continue;
    const text = describe(k, node.in[k]);
    if (text !== null) parts.push(text);
  }
  return parts.length === 0 ? null : parts.slice(0, MAX_PARTS).join(" · ");
}
