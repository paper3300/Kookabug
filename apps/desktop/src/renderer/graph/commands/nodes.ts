// 노드 더하기·옮기기·지우기 (M2 계획 2.6 "편집 규칙", T9). 명령은 자기가 바꾸는 경로만 바꾼다.
// 모르는 키(최상위·노드·in·config·layout)와 모르는 노드의 in·config·next·version은 그대로다
import { findLinks, isObject, own, type GraphValue } from "../model";
import { deleteIn, getIn, setIn } from "../valueOps";

export interface NewNode {
  id: string;
  type: string;
  version: number;
  x: number;
  y: number;
  /** 노드 타입의 플러그인. 그래프 plugins에 없으면 이 판으로 적는다 (있으면 그대로) */
  plugin?: { id: string; version: string } | null;
}

/** 좌표는 정수로 반올림한다 (-0은 0) */
export function roundCoord(n: number): number {
  return Math.round(n) + 0;
}

/**
 * 노드를 더한다. 노드 스키마 기본값으로 `in`을 채우지 않는다(기본값은 실행기가 쓴다). 좌표는
 * `layout.nodes`에 쓴다
 */
export function addNode(value: GraphValue, node: NewNode): GraphValue {
  if (isObject(own(own(value, "nodes"), node.id))) throw new Error(`이미 있는 노드 ID: ${node.id}`);
  let out = setIn(value, ["nodes", node.id], { type: node.type, version: node.version });
  out = setIn(out, ["layout", "nodes", node.id], { x: roundCoord(node.x), y: roundCoord(node.y) });
  const plugin = node.plugin;
  if (plugin && plugin.id !== "" && own(own(out, "plugins"), plugin.id) === undefined) {
    out = setIn(out, ["plugins", plugin.id], plugin.version);
  }
  return out;
}

export interface Move {
  id: string;
  x: number;
  y: number;
}

/** 노드를 옮긴다. 좌표 객체의 다른 키는 그대로 두고 x·y만 쓴다. 없는 노드는 무시한다 */
export function moveNodes(value: GraphValue, moves: readonly Move[]): GraphValue {
  let out = value;
  for (const m of moves) {
    if (!isObject(own(own(out, "nodes"), m.id))) continue;
    const at = ["layout", "nodes", m.id];
    const x = roundCoord(m.x);
    const y = roundCoord(m.y);
    if (isObject(getIn(out, at))) {
      out = setIn(out, [...at, "x"], x);
      out = setIn(out, [...at, "y"], y);
    } else {
      out = setIn(out, at, { x, y });
    }
  }
  return out;
}

/**
 * 노드를 지운다 (2.6 정리 규칙): 그 노드 키, `layout.nodes`의 그 키, 다른 노드 `next`에서 그 노드를 가리키는
 * 출구, `$link`로 그 노드를 읽는 핀(그 핀 키 전체), 접힌 그룹 `nodes` 목록의 그 ID. 비게 된 `next`·`in`은
 * 함께 지운다. 지운 결과로 생기는 검증 오류는 문제 패널에 나온다
 */
export function deleteNodes(value: GraphValue, ids: Iterable<string>): GraphValue {
  const gone = new Set<string>();
  const nodes = own(value, "nodes");
  for (const id of ids) if (isObject(own(nodes, id))) gone.add(id);
  if (gone.size === 0 || !isObject(nodes)) return value;
  let out = value;
  for (const id of Object.keys(nodes)) {
    if (gone.has(id)) continue;
    const node = nodes[id];
    if (!isObject(node)) continue;
    const next = own(node, "next");
    if (isObject(next)) {
      for (const exit of Object.keys(next)) {
        const to = next[exit];
        if (typeof to === "string" && gone.has(to)) out = deleteIn(out, ["nodes", id, "next", exit], 1);
      }
    }
    const inputs = own(node, "in");
    if (isObject(inputs)) {
      for (const pin of Object.keys(inputs)) {
        if (findLinks(inputs[pin]).some((l) => gone.has(l.node))) out = deleteIn(out, ["nodes", id, "in", pin], 1);
      }
    }
  }
  for (const id of gone) {
    out = deleteIn(out, ["nodes", id]);
    out = deleteIn(out, ["layout", "nodes", id]);
  }
  const groups = getIn(out, ["layout", "collapsed"]);
  if (isObject(groups)) {
    for (const g of Object.keys(groups)) {
      const members = own(groups[g], "nodes");
      if (!Array.isArray(members) || !members.some((m) => typeof m === "string" && gone.has(m))) continue;
      out = setIn(
        out,
        ["layout", "collapsed", g, "nodes"],
        members.filter((m) => !(typeof m === "string" && gone.has(m))),
      );
    }
  }
  return out;
}
