// 화면 지도 카드 배치 (M7 B5): 자동 배치(시작 화면에서 넓이 우선 단)·저장 자리 우선·간선 경로·확대 단계
import { describe, expect, test } from "vitest";
import {
  autoLayout,
  bounds,
  CARD_H,
  CARD_W,
  COL_GAP,
  edgePath,
  fitZoom,
  MARGIN,
  mergeLayout,
  nextZoom,
  positionsToSave,
  ROW_GAP,
} from "./layout";

const col = (n: number) => MARGIN + n * (CARD_W + COL_GAP);
const row = (n: number) => MARGIN + n * (CARD_H + ROW_GAP);

describe("autoLayout", () => {
  test("시작 화면이 첫 단, 이동을 따라 다음 단, 단 안은 발견 순서", () => {
    const nodes = ["lobby", "bag", "upgrade", "shop", "result"];
    const edges = [
      { from: "lobby", to: "bag" },
      { from: "lobby", to: "shop" },
      { from: "bag", to: "upgrade" },
      { from: "upgrade", to: "result" },
      { from: "result", to: "upgrade" },
    ];
    const at = autoLayout(nodes, edges, "lobby");
    expect(at.get("lobby")).toEqual({ x: col(0), y: row(0) });
    expect(at.get("bag")).toEqual({ x: col(1), y: row(0) });
    expect(at.get("shop")).toEqual({ x: col(1), y: row(1) });
    expect(at.get("upgrade")).toEqual({ x: col(2), y: row(0) });
    expect(at.get("result")).toEqual({ x: col(3), y: row(0) });
  });

  test("닿지 않는 카드(다른 세션 후보·고립 화면)는 마지막 단 뒤에 이어 붙인다", () => {
    const at = autoLayout(["a", "b", "x", "y"], [{ from: "a", to: "b" }, { from: "x", to: "y" }], "a");
    expect(at.get("x")).toEqual({ x: col(2), y: row(0) });
    expect(at.get("y")).toEqual({ x: col(3), y: row(0) });
  });

  test("시작 화면이 없거나 모르는 이름이면 노드 순서대로, 끝이 null·모르는 노드인 간선은 무시", () => {
    const at = autoLayout(["a", "b"], [{ from: "a", to: null }, { from: "a", to: "zz" }, { from: "a", to: "a" }], null);
    expect(at.get("a")).toEqual({ x: col(0), y: row(0) });
    expect(at.get("b")).toEqual({ x: col(1), y: row(0) });
    expect(autoLayout([], [], "a").size).toBe(0);
  });

  test("들어오는 이동만 있는 화면도 시작 화면 근처에 놓인다 (되돌아가는 이동)", () => {
    const at = autoLayout(["lobby", "popup"], [{ from: "popup", to: "lobby" }], "lobby");
    expect(at.get("popup")).toEqual({ x: col(1), y: row(0) });
  });

  test("단이 MAX_COLS를 넘으면 아래 묶음으로 접는다 (묶음 높이 = 그 묶음의 가장 긴 단)", () => {
    const nodes = ["a", "b", "b2", "c", "d", "e", "f"];
    const edges = [
      { from: "a", to: "b" },
      { from: "a", to: "b2" },
      { from: "b", to: "c" },
      { from: "c", to: "d" },
      { from: "d", to: "e" },
      { from: "e", to: "f" },
    ];
    const at = autoLayout(nodes, edges, "a", 4);
    expect(at.get("d")).toEqual({ x: col(3), y: row(0) });
    // 둘째 묶음: 첫 묶음이 2줄(b·b2)이므로 그 아래 + 묶음 간격
    const second = MARGIN + 2 * (CARD_H + ROW_GAP) + ROW_GAP;
    expect(at.get("e")).toEqual({ x: col(0), y: second });
    expect(at.get("f")).toEqual({ x: col(1), y: second });
    expect(Math.max(...[...at.values()].map((p) => p.x))).toBeLessThan(col(4));
  });

  test("카드 300개도 겹치지 않는다", () => {
    const nodes = Array.from({ length: 300 }, (_, i) => `n${i}`);
    const edges = nodes.slice(1).map((n, i) => ({ from: `n${Math.floor(i / 3)}`, to: n }));
    const at = autoLayout(nodes, edges, "n0");
    const seen = new Set([...at.values()].map((p) => `${p.x},${p.y}`));
    expect(seen.size).toBe(300);
  });
});

describe("mergeLayout·positionsToSave", () => {
  const auto = new Map([
    ["a", { x: 40, y: 40 }],
    ["b", { x: 350, y: 40 }],
  ]);

  test("저장한 자리가 먼저, 없는 카드의 자리는 버린다", () => {
    const merged = mergeLayout(auto, { b: [10, 20], gone: [1, 2], bad: [1] });
    expect(merged.get("a")).toEqual({ x: 40, y: 40 });
    expect(merged.get("b")).toEqual({ x: 10, y: 20 });
    expect(merged.has("gone")).toBe(false);
    expect(mergeLayout(auto, undefined)).toEqual(auto);
  });

  test("저장할 자리는 사람이 옮긴 카드와 전에 저장한 카드만", () => {
    const current = new Map([
      ["a", { x: 40, y: 40 }],
      ["b", { x: 99.6, y: 20.2 }],
    ]);
    expect(positionsToSave(current, auto, undefined)).toEqual({ b: [100, 20] });
    expect(positionsToSave(current, auto, { a: [40, 40] })).toEqual({ a: [40, 40], b: [100, 20] });
  });
});

describe("bounds·edgePath·nextZoom", () => {
  test("bounds는 카드 크기와 여백까지", () => {
    expect(bounds([{ x: 40, y: 40 }])).toEqual({ width: 40 + CARD_W + MARGIN, height: 40 + CARD_H + MARGIN });
    expect(bounds([])).toEqual({ width: 0, height: 0 });
  });

  test("오른쪽 대상은 베지어, 이름표는 가운데", () => {
    const { d, label } = edgePath({ x: 0, y: 0 }, { x: 400, y: 0 });
    expect(d.startsWith(`M${CARD_W} ${CARD_H / 2} C`)).toBe(true);
    expect(label).toEqual({ x: (CARD_W + 400) / 2, y: CARD_H / 2 });
  });

  test("왼쪽 대상은 두 카드 아래로 돌아간다", () => {
    const { d, label } = edgePath({ x: 400, y: 0 }, { x: 0, y: 100 });
    expect(d).toContain(" S");
    expect(label.y).toBeGreaterThan(100 + CARD_H);
  });

  test("처음 보기 화면에 맞춤: 들어가는 가장 큰 단계, 100% 넘지 않음, 30% 아래로 안 감", () => {
    expect(fitZoom({ width: 1300, height: 700 }, { width: 1100, height: 700 })).toBe(0.8);
    expect(fitZoom({ width: 500, height: 300 }, { width: 1100, height: 700 })).toBe(1);
    expect(fitZoom({ width: 20_000, height: 9_000 }, { width: 1100, height: 700 })).toBe(0.3);
    expect(fitZoom({ width: 0, height: 0 }, { width: 1100, height: 700 })).toBe(0.7);
  });

  test("확대 단계", () => {
    expect(nextZoom(0.7, 1)).toBe(0.8);
    expect(nextZoom(0.7, -1)).toBe(0.6);
    expect(nextZoom(1.5, 1)).toBe(1.5);
    expect(nextZoom(0.3, -1)).toBe(0.3);
    expect(nextZoom(0.75, -1)).toBe(0.7);
  });
});
