// 속성 편집 명령 (M2 계획 2.6 "편집 규칙", T10). 명령은 값 → 새 값 순수 함수이고 자기가 바꾸는 경로만 바꾼다.
// 모르는 키(노드·in·config의 처음 보는 키)와 version·next는 건드리지 않는다
import { isObject, own, type GraphValue, type JsonObject } from "../model";
import { deleteIn, jsonEqual, setIn } from "../valueOps";

/** 노드 안에서 고치는 객체: 입력 핀 값(in) 또는 노드 설정(config) */
export type NodeField = "in" | "config";

function nodeExists(value: GraphValue, node: string): boolean {
  return isObject(own(own(value, "nodes"), node));
}

/** 핀(또는 config 키) 값을 쓴다. 같은 값이면 같은 루트를 돌려준다(기록 없음) */
export function setNodeValue(value: GraphValue, node: string, field: NodeField, key: string, v: unknown): GraphValue {
  if (!nodeExists(value, node)) return value;
  const old = own(own(own(own(value, "nodes"), node), field), key);
  if (old !== undefined && jsonEqual(old, v)) return value;
  return setIn(value, ["nodes", node, field, key], v);
}

/** 핀(또는 config 키)을 지운다 (기본값으로). 비게 된 in·config는 함께 지운다 (T9 연결 끊기와 같은 규칙) */
export function clearNodeValue(value: GraphValue, node: string, field: NodeField, key: string): GraphValue {
  return deleteIn(value, ["nodes", node, field, key], 1);
}

/** 제목을 바꾼다. 빈 글자면 title 키를 지운다 (노드 스키마 제목으로 보인다). ID는 그대로다 (2.6) */
export function setNodeTitle(value: GraphValue, node: string, title: string): GraphValue {
  if (!nodeExists(value, node)) return value;
  if (title === "") return deleteIn(value, ["nodes", node, "title"]);
  return setIn(value, ["nodes", node, "title"], title);
}

/**
 * in·config 객체를 새 객체로 바꾸되 바뀐 키만 쓴다 (모르는 노드의 JSON 상자, 2.11). 값이 같은 키는 앞 값 그대로
 * 두고(키 순서·원래 수 표기 유지), 없어진 키만 지우고, 새 키는 끝에 붙는다. 비게 되면 그 객체를 지운다
 */
export function replaceNodeObject(value: GraphValue, node: string, field: NodeField, next: JsonObject): GraphValue {
  if (!nodeExists(value, node)) return value;
  const current = own(own(own(value, "nodes"), node), field);
  const old: JsonObject = isObject(current) ? current : {};
  let out = value;
  if (current !== undefined && !isObject(current)) {
    // 객체가 아니던 자리(틀린 값)를 새 객체로 바꾼다
    return Object.keys(next).length === 0 ? deleteIn(value, ["nodes", node, field]) : setIn(value, ["nodes", node, field], next);
  }
  for (const k of Object.keys(next)) {
    if (Object.hasOwn(old, k) && jsonEqual(old[k], next[k])) continue;
    out = setIn(out, ["nodes", node, field, k], next[k]);
  }
  for (const k of Object.keys(old)) {
    if (!Object.hasOwn(next, k)) out = deleteIn(out, ["nodes", node, field, k], 1);
  }
  return out;
}

/**
 * 노드 "실행 전" 옵션 `focus_before_input` (UX4): null = 그래프 기본값을 따름(키 지움), true·false = 그 값.
 * config가 아니라 노드 최상위 키다 (노드 설정을 더럽히지 않는다)
 */
export function setNodeFocus(value: GraphValue, node: string, focus: boolean | null): GraphValue {
  if (!nodeExists(value, node)) return value;
  if (focus === null) return deleteIn(value, ["nodes", node, "focus_before_input"]);
  if (own(own(own(value, "nodes"), node), "focus_before_input") === focus) return value;
  return setIn(value, ["nodes", node, "focus_before_input"], focus);
}

/** 그래프 기본값 "입력 전 게임 창 앞으로" (UX4): 켜짐이 기본이라 켜면 키를 지우고 끄면 false를 쓴다 */
export function setGraphFocus(value: GraphValue, on: boolean): GraphValue {
  if (on) return own(value, "focus_before_input") === undefined ? value : deleteIn(value, ["focus_before_input"]);
  if (own(value, "focus_before_input") === false) return value;
  return setIn(value, ["focus_before_input"], false);
}

/** 그래프 기본값 (없으면 켜짐) */
export function graphFocus(value: GraphValue | null): boolean {
  return value === null || own(value, "focus_before_input") !== false;
}

/** 노드 옵션: null = 그래프를 따름 */
export function nodeFocus(value: GraphValue | null, node: string): boolean | null {
  const v = value === null ? undefined : own(own(own(value, "nodes"), node), "focus_before_input");
  return typeof v === "boolean" ? v : null;
}
