// target 사양 편집 (M2 계획 2.9 "사양 편집", M4 T11 확장). 값(JSON 트리)은 바꾸지 않고 바뀐 경로만 새로 만든다
// (graph/valueOps). 편집기가 모르는 키·고치지 않은 키는 그대로 둔다 (원문 보존·최소 변경)
// - 임계값: match.threshold (0.50~0.99, 0.01 단위). 기본값은 생성 상수 DEFAULT_MATCH_THRESHOLD
//   (target.schema.json default 하나, Python kookabug_platform.vision.DEFAULT_THRESHOLD와 같은 출처 — M4 T12)
// - 색까지 확인: match.rgb (기본 true), 색 허용치: match.color_tolerance (0~255 정수, 기본 DEFAULT_COLOR_TOLERANCE)
// - 배율 0.8–1.25: match.methods에 template_multiscale이 있는지. 끄면 ["template"]. 다시 켜면 처음 열었을 때의
//   값(없었으면 키를 지워 기본값)으로 돌아간다
// - 민감 대상: sensitive (켜면 true, 끄면 처음 값이 false였으면 false, 아니면 키를 지운다)
// - 클릭 지점: click.anchor(9분할)·click.offset [dx, dy]
// - 검색 범위: search.region (클라이언트 기준 정규화 [x, y, w, h]). 숫자 칸 하나씩 고치기(editRegion)·지우기
// - "여러 개면 좌상단부터"는 target 형식에 없어 다루지 않는다 (U7)
import { DEFAULT_COLOR_TOLERANCE, DEFAULT_MATCH_THRESHOLD } from "@kookabug/schema";
import { isObject, type JsonObject } from "../graph/model";
import { deleteIn, getIn, jsonEqual, setIn } from "../graph/valueOps";
import { isAnchor, type Anchor } from "./geometry";

export type TargetSpec = JsonObject;

export const DEFAULT_THRESHOLD = DEFAULT_MATCH_THRESHOLD;
export { DEFAULT_COLOR_TOLERANCE };
export const COLOR_TOLERANCE_MAX = 255;
export const THRESHOLD_MIN = 0.5;
export const THRESHOLD_MAX = 0.99;
export const DEFAULT_METHODS = ["template_multiscale", "template"] as const;
export const TARGET_FORMAT = "kookabug.target/0";

export interface SpecFields {
  threshold: number;
  rgb: boolean;
  multiscale: boolean;
  anchor: Anchor;
  offset: [number, number];
  region: [number, number, number, number] | null;
  sensitive: boolean;
  colorTolerance: number;
}

function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/** 편집기가 보이는 값 (없거나 틀린 칸은 기본값) */
export function specFields(spec: TargetSpec): SpecFields {
  const methods = getIn(spec, ["match", "methods"]);
  const offset = getIn(spec, ["click", "offset"]);
  const region = getIn(spec, ["search", "region"]);
  const anchor = getIn(spec, ["click", "anchor"]);
  return {
    threshold: num(getIn(spec, ["match", "threshold"])) ?? DEFAULT_THRESHOLD,
    rgb: getIn(spec, ["match", "rgb"]) !== false,
    multiscale: Array.isArray(methods) ? methods.includes("template_multiscale") : true,
    anchor: isAnchor(anchor) ? anchor : "center",
    offset:
      Array.isArray(offset) && offset.length === 2 && num(offset[0]) !== null && num(offset[1]) !== null
        ? [offset[0] as number, offset[1] as number]
        : [0, 0],
    region:
      Array.isArray(region) && region.length === 4 && region.every((v) => num(v) !== null)
        ? (region as [number, number, number, number])
        : null,
    sensitive: spec.sensitive === true,
    colorTolerance: num(getIn(spec, ["match", "color_tolerance"])) ?? DEFAULT_COLOR_TOLERANCE,
  };
}

/** 슬라이더 값을 0.01 단위·범위 안으로 */
export function clampThreshold(v: number): number {
  const r = Math.round(v * 100) / 100;
  return Math.min(THRESHOLD_MAX, Math.max(THRESHOLD_MIN, r));
}

/** 객체가 아니던 중간 칸(match·click·search)은 객체로 바꾼다 */
function ensureObject(spec: TargetSpec, key: string): TargetSpec {
  return isObject(getIn(spec, [key])) ? spec : setIn(spec, [key], {});
}

export function setThreshold(spec: TargetSpec, v: number): TargetSpec {
  return setIn(ensureObject(spec, "match"), ["match", "threshold"], clampThreshold(v));
}

export function setRgb(spec: TargetSpec, on: boolean): TargetSpec {
  return setIn(ensureObject(spec, "match"), ["match", "rgb"], on);
}

/** original: 처음 열었을 때의 사양 (다시 켤 때 돌아갈 값) */
export function setMultiscale(spec: TargetSpec, on: boolean, original: TargetSpec | null): TargetSpec {
  if (!on) return setIn(ensureObject(spec, "match"), ["match", "methods"], ["template"]);
  const before = original === null ? undefined : getIn(original, ["match", "methods"]);
  if (Array.isArray(before) && before.includes("template_multiscale")) {
    return setIn(ensureObject(spec, "match"), ["match", "methods"], before);
  }
  // 처음에 match도 없었으면 비게 된 match까지 지워 처음 값으로 돌아간다
  if (before === undefined) return deleteIn(spec, ["match", "methods"], original !== null && getIn(original, ["match"]) === undefined ? 1 : 0);
  return setIn(ensureObject(spec, "match"), ["match", "methods"], [...DEFAULT_METHODS]);
}

export function setAnchor(spec: TargetSpec, anchor: Anchor): TargetSpec {
  return setIn(ensureObject(spec, "click"), ["click", "anchor"], anchor);
}

export function setOffset(spec: TargetSpec, offset: readonly [number, number]): TargetSpec {
  return setIn(ensureObject(spec, "click"), ["click", "offset"], [offset[0], offset[1]]);
}

export function setRegion(spec: TargetSpec, region: readonly number[] | null): TargetSpec {
  if (region === null) return getIn(spec, ["search", "region"]) === undefined ? spec : deleteIn(spec, ["search", "region"], 1);
  return setIn(ensureObject(spec, "search"), ["search", "region"], [...region]);
}

/** original: 처음 열었을 때의 사양. 끌 때 처음에 "sensitive": false가 있었으면 그 값으로, 아니면 키를 지운다 */
export function setSensitive(spec: TargetSpec, on: boolean, original: TargetSpec | null): TargetSpec {
  if (on) return setIn(spec, ["sensitive"], true);
  if (original !== null && original.sensitive === false) return setIn(spec, ["sensitive"], false);
  return spec.sensitive === undefined ? spec : deleteIn(spec, ["sensitive"]);
}

/** 색 허용치를 0~255 정수로 */
export function clampColorTolerance(v: number): number {
  return Math.min(COLOR_TOLERANCE_MAX, Math.max(0, Math.round(v)));
}

export function setColorTolerance(spec: TargetSpec, v: number): TargetSpec {
  return setIn(ensureObject(spec, "match"), ["match", "color_tolerance"], clampColorTolerance(v));
}

const REGION_DIGITS = 1e6;

/**
 * 검색 범위 숫자 칸 하나(0 x · 1 y · 2 w · 3 h, 정규화 0~1)를 고친 새 범위. 범위가 없으면 화면 전체에서 시작한다.
 * 오른쪽·아래가 1을 넘으면 너비·높이를 줄인다. 너비·높이가 0이 되면 null (받아들이지 않는다)
 */
export function editRegion(
  region: readonly number[] | null,
  index: 0 | 1 | 2 | 3,
  value: number,
): [number, number, number, number] | null {
  if (!Number.isFinite(value)) return null;
  const next: [number, number, number, number] = region === null ? [0, 0, 1, 1] : [region[0], region[1], region[2], region[3]];
  next[index] = Math.round(Math.min(1, Math.max(0, value)) * REGION_DIGITS) / REGION_DIGITS;
  next[2] = Math.min(next[2], 1 - next[0]);
  next[3] = Math.min(next[3], 1 - next[1]);
  if (next[2] <= 0 || next[3] <= 0) return null;
  return next.map((v) => Math.round(v * REGION_DIGITS) / REGION_DIGITS) as [number, number, number, number];
}

/**
 * 요청을 보낸 뒤 사용자가 바꾼 것만 서버 사양 위에 다시 얹는다 (T12 검수 1차 Mid 1). sent = 보낸 사양,
 * current = 지금 버퍼, server = 저장 뒤 디스크 사양(daemon이 채운 image·recorded·맞춘 검색 범위). sent와 current가
 * 다른 경로만 current 값으로 바꾸거나 지우고, 나머지는 server 값이다. 객체는 키별로 내려가고 배열은 통째 값이다
 */
export function rebaseSpec(sent: unknown, current: unknown, server: TargetSpec): TargetSpec {
  return rebase(sent, current, server) as TargetSpec;
}

function rebase(sent: unknown, current: unknown, server: unknown): unknown {
  if (jsonEqual(sent, current)) return server;
  if (!isObject(sent) || !isObject(current) || !isObject(server)) return current;
  let out: unknown = server;
  for (const k of new Set([...Object.keys(sent), ...Object.keys(current)])) {
    const had = Object.hasOwn(sent, k);
    const has = Object.hasOwn(current, k);
    if (had && has && jsonEqual(sent[k], current[k])) continue;
    if (!has) {
      out = deleteIn(out, [k]);
      continue;
    }
    const base = Object.hasOwn(server, k) ? server[k] : undefined;
    out = setIn(out, [k], had && base !== undefined ? rebase(sent[k], current[k], base) : current[k]);
  }
  return out;
}

/** 새 target의 처음 사양 (daemon이 format·image·recorded를 채운다) */
export function newSpec(): TargetSpec {
  return { format: TARGET_FORMAT };
}

/** 오프셋 표시: 정수면 그대로, 아니면 소수 한 자리 */
export function formatOffset(v: number): string {
  return Number.isInteger(v) ? String(v) : v.toFixed(1);
}
