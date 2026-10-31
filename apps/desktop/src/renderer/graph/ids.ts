// 노드 ID (M2 계획 2.6 "편집 규칙"): `n_` + 무작위 8자(소문자 base32). 만들 때 정하고 바꾸지 않는다.
// 문서의 모든 ID(노드·접힌 그룹·주석)와 겹치면 다시 뽑는다
import { isObject, own, type GraphValue } from "./model";

const ALPHABET = "abcdefghijklmnopqrstuvwxyz234567";
export const NODE_ID_PATTERN = /^n_[a-z2-7]{8}$/;

/** 0~255 바이트 n개 (검사가 바꿔 끼운다) */
export type RandomBytes = (n: number) => Uint8Array;

export const cryptoBytes: RandomBytes = (n) => crypto.getRandomValues(new Uint8Array(n));

/** 문서가 쓰는 ID 전부: 노드, layout.collapsed 그룹, layout.comments 주석 */
export function takenIds(value: GraphValue): Set<string> {
  const out = new Set<string>();
  const add = (obj: unknown) => {
    if (isObject(obj)) for (const k of Object.keys(obj)) out.add(k);
  };
  add(own(value, "nodes"));
  const layout = own(value, "layout");
  add(own(layout, "collapsed"));
  add(own(layout, "comments"));
  return out;
}

export function newNodeId(taken: ReadonlySet<string>, random: RandomBytes = cryptoBytes): string {
  for (let attempt = 0; attempt < 1000; attempt++) {
    const bytes = random(8);
    let id = "n_";
    for (let i = 0; i < 8; i++) id += ALPHABET[bytes[i] & 31];
    if (!taken.has(id)) return id;
  }
  throw new Error("겹치지 않는 노드 ID를 만들지 못했다");
}
