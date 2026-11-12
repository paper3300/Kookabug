// 탭 오른쪽 클릭 메뉴 (UX4): 닫기·다른 탭 닫기·모든 탭 닫기, 저장 안 된 탭 여럿은 확인 한 번으로 묶고 취소면 아무것도 닫지 않는다
import { beforeEach, describe, expect, test } from "vitest";
import { tabMenuItems } from "../app/Editor";
import { moveNodes } from "../graph/commands";
import { openReportsTab } from "../reports/reportsStore";
import { finish, useDialog } from "./dialog";
import { applyEdit, getDoc, resetDocuments, setDocumentsConnection } from "./documents";
import { requestCloseTabs } from "./editing";
import { openTab, useTabs } from "./tabs";

interface Call {
  method: string;
  params: Record<string, unknown>;
  resolve(v: unknown): void;
}

const calls: Call[] = [];
(globalThis as unknown as { kookabug: unknown }).kookabug = {
  rpc(method: string, params: Record<string, unknown>) {
    return new Promise((resolve) => calls.push({ method, params, resolve }));
  },
  on() {
    return () => {};
  },
};

const A = "tests/a.graph.json";
const B = "tests/b.graph.json";
const C = "tests/c.graph.json";
const tick = () => new Promise((r) => setTimeout(r, 0));
const paths = () => useTabs.getState().tabs.map((t) => t.path);
const dirty = (p: string) => applyEdit(p, (v) => moveNodes(v, [{ id: "n_a", x: 5, y: 5 }]));

async function open(path: string): Promise<void> {
  openTab({ path, kind: "graph", graphKind: "test" });
  await tick();
  calls
    .filter((c) => c.method === "graph.open" && c.params.path === path)
    .at(-1)!
    .resolve({
      doc_id: path,
      revision: "r1",
      value: { nodes: { n_a: { type: "core.flow.delay", version: 1 } } },
      canonical: true,
      diagnostics: [],
      shapes: {},
    });
  await tick();
  expect(getDoc(path)?.status).toBe("ready");
}

beforeEach(async () => {
  if (useDialog.getState().current !== null) finish({ value: "cancel", text: "" });
  useTabs.setState({ tabs: [], active: null });
  resetDocuments();
  calls.length = 0;
  setDocumentsConnection("s:1");
  await open(A);
  await open(B);
  await open(C);
});

describe("탭 메뉴", () => {
  test("세 항목, 다른 탭 닫기는 고른 탭만 남기고 그 탭을 연다 (저장 안 된 탭이 없으면 묻지 않는다)", async () => {
    openReportsTab();
    const items = tabMenuItems(B, paths());
    expect(items.map((i) => i.label)).toEqual(["닫기", "다른 탭 닫기", "모든 탭 닫기"]);
    items[1]!.onSelect();
    await tick();
    expect(useDialog.getState().current).toBeNull();
    expect(paths()).toEqual([B]);
    expect(useTabs.getState().active).toBe(B);
  });

  test("모든 탭 닫기 / 닫기", async () => {
    tabMenuItems(A, paths())[0]!.onSelect();
    await tick();
    expect(paths()).toEqual([B, C]);
    tabMenuItems(B, paths())[2]!.onSelect();
    await tick();
    expect(paths()).toEqual([]);
  });

  test("탭이 하나면 다른 탭 닫기는 꺼진다", () => {
    expect(tabMenuItems(A, [A])[1]!.disabled).toBe(true);
  });
});

describe("저장 안 된 탭 묶음 확인", () => {
  test("여럿이면 한 번만 묻고, 취소면 아무 탭도 닫지 않는다", async () => {
    dirty(A);
    dirty(B);
    const closing = requestCloseTabs([A, B, C]);
    await tick();
    expect(useDialog.getState().current?.title).toBe("저장 안 된 탭이 2개 있어요");
    finish({ value: "cancel", text: "" });
    expect(await closing).toBe(false);
    expect(paths()).toEqual([A, B, C]);
    expect(getDoc(A)?.dirty).toBe(true);
  });

  test("저장 안 함이면 한 번 묻고 모두 닫는다", async () => {
    dirty(A);
    dirty(C);
    const closing = requestCloseTabs([A, B, C]);
    await tick();
    finish({ value: "discard", text: "" });
    expect(await closing).toBe(true);
    expect(paths()).toEqual([]);
  });

  test("하나면 탭 하나 닫을 때와 같은 질문, 저장하면 저장한 뒤 닫는다", async () => {
    dirty(B);
    const closing = requestCloseTabs([A, B]);
    await tick();
    expect(useDialog.getState().current?.title).toBe("'b'의 변경을 저장할까요?");
    finish({ value: "save", text: "" });
    await tick();
    const save = calls.find((c) => c.method === "graph.save");
    expect(save?.params.path ?? save?.params.doc_id).toBeDefined();
    save!.resolve({ revision: "r2", wrote: true, canonicalized: false, diagnostics: [] });
    expect(await closing).toBe(true);
    expect(paths()).toEqual([C]);
  });
});
