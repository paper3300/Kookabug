// 값 트리 편집 도우미 (M2 계획 2.6 "편집 규칙", T9). 값은 바꾸지 않고 바뀐 경로만 새로 만든 사본을 돌려준다
// (구조 공유). 실행 취소 기록이 앞 값을 그대로 들 수 있다.
// - 키 쓰기는 Object.defineProperty만 쓴다. `obj[key] = v`·Object.assign은 `__proto__` 키에서 프로토타입을
//   바꾸고, `constructor`는 프로토타입 쪽 이름이라 읽을 때 Object.hasOwn으로만 본다 (2.6 `__proto__` 키)
// - 키 순서는 그대로 둔다. 새 키는 끝에 붙는다 (canonical 저장은 키를 정렬하고, 무수정이면 원문을 쓴다)
import { isObject, type JsonObject } from "./model";

export type Key = string | number;

/** 자기 키 그대로 얕은 사본 (`__proto__`도 보통 키로) */
export function copyObject(obj: JsonObject): JsonObject {
  const out: JsonObject = {};
  for (const k of Object.keys(obj)) defineKey(out, k, obj[k]);
  return out;
}

function defineKey(obj: JsonObject, key: string, value: unknown): void {
  Object.defineProperty(obj, key, { value, writable: true, enumerable: true, configurable: true });
}

/** 자기 속성만 따라 읽는다. 없거나 모양이 틀리면 undefined */
export function getIn(root: unknown, path: readonly Key[]): unknown {
  let cur: unknown = root;
  for (const k of path) {
    if (typeof k === "number") {
      if (!Array.isArray(cur) || k < 0 || k >= cur.length) return undefined;
      cur = cur[k];
    } else {
      if (!isObject(cur) || !Object.hasOwn(cur, k)) return undefined;
      cur = cur[k];
    }
  }
  return cur;
}

/**
 * 경로에 값을 쓴 새 루트. 중간 객체가 없거나 객체가 아니면 빈 객체로 만든다(문자열 키). 배열 원소는
 * 있는 자리만 바꾼다(배열 밖 번호는 던진다)
 */
export function setIn<T>(root: T, path: readonly Key[], value: unknown): T {
  if (path.length === 0) return value as T;
  const [head, ...rest] = path;
  if (typeof head === "number") {
    if (!Array.isArray(root) || head < 0 || head >= root.length) throw new RangeError(`배열 밖 위치: ${head}`);
    const copy = root.slice();
    copy[head] = setIn(copy[head], rest, value);
    return copy as T;
  }
  const base: JsonObject = isObject(root) ? root : {};
  const child = Object.hasOwn(base, head) ? base[head] : undefined;
  const next = setIn(rest.length > 0 && !isObject(child) && !Array.isArray(child) ? {} : child, rest, value);
  if (Object.hasOwn(base, head) && Object.is(base[head], next)) return root;
  const copy = copyObject(base);
  defineKey(copy, head, next);
  return copy as T;
}

/**
 * 객체 키 하나를 지운 새 루트. 없으면 같은 루트를 돌려준다.
 * prune: 지운 뒤 비게 된 부모 객체를 그 부모에서도 지운다 (경로 길이로 깊이를 정한다. 예: `next` 맵)
 */
export function deleteIn<T>(root: T, path: readonly Key[], prune = 0): T {
  if (path.length === 0) return root;
  const parentPath = path.slice(0, -1);
  const key = path[path.length - 1];
  const parent = getIn(root, parentPath);
  if (typeof key !== "string" || !isObject(parent) || !Object.hasOwn(parent, key)) return root;
  const copy: JsonObject = {};
  for (const k of Object.keys(parent)) if (k !== key) defineKey(copy, k, parent[k]);
  if (prune > 0 && Object.keys(copy).length === 0 && parentPath.length > 0) return deleteIn(root, parentPath, prune - 1);
  return setIn(root, parentPath, copy);
}

/**
 * JSON 값 비교 (키 순서 무관). 수는 JS 수 비교다(JS에는 1과 1.0의 구분이 없다. Python `json_equal`의
 * 1 == 1.0과 같다). -0과 0은 같게 본다
 */
export function jsonEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (Array.isArray(a)) {
    return Array.isArray(b) && a.length === b.length && a.every((x, i) => jsonEqual(x, b[i]));
  }
  if (isObject(a)) {
    if (!isObject(b)) return false;
    const ka = Object.keys(a);
    if (ka.length !== Object.keys(b).length) return false;
    return ka.every((k) => Object.hasOwn(b, k) && jsonEqual(a[k], b[k]));
  }
  return false;
}
