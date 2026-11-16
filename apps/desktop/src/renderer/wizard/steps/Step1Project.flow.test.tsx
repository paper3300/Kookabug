// UX10 D (검수1 Mid): 실제 Step1Project의 위치 칸 onChange → "만들기" 단추(StepShell primary) 켜짐 → 누름(primary.run) →
// 정리한 parent로 workspaceCreate 호출 → 거부 글이 role=alert로 보이는 흐름을 컴포넌트 그대로 지난다.
// 컴포넌트는 그리지 않고 함수로 불러 나온 요소 트리를 따라간다: React 훅만 작은 대역(상태 칸)으로 바꾼다 (Step5Agent.test와 같은 방식)
import type { ReactElement, ReactNode } from "react";
import { beforeEach, describe, expect, test, vi } from "vitest";

const H = vi.hoisted(() => ({ slots: [] as unknown[], i: 0 }));

vi.mock("react", async (original) => {
  const React = await original<typeof import("react")>();
  const useState = (init: unknown) => {
    const i = H.i++;
    if (!(i in H.slots)) H.slots[i] = typeof init === "function" ? (init as () => unknown)() : init;
    const set = (v: unknown) => {
      H.slots[i] = typeof v === "function" ? (v as (x: unknown) => unknown)(H.slots[i]) : v;
    };
    return [H.slots[i], set];
  };
  return { ...React, default: React, useState };
});

const { Step1Project } = await import("./Step1Project");

type Props = Record<string, unknown> & { children?: ReactNode };

/** 함수 컴포넌트를 한 번 부른다 (훅 칸 번호를 처음부터) */
function render(): ReactElement<Props> {
  H.i = 0;
  return Step1Project() as ReactElement<Props>;
}

/** 요소 트리를 펼친다 (속성 안의 요소 — StepShell의 right 등 — 와 children 모두) */
function walk(node: unknown, out: ReactElement<Props>[] = []): ReactElement<Props>[] {
  if (Array.isArray(node)) {
    for (const n of node) walk(n, out);
  } else if (node !== null && typeof node === "object" && "props" in node) {
    const el = node as ReactElement<Props>;
    out.push(el);
    for (const value of Object.values(el.props)) walk(value, out);
  }
  return out;
}

const find = (tree: ReactElement<Props>, pred: (p: Props) => boolean) => walk(tree).find((el) => pred(el.props));
const locationInput = (tree: ReactElement<Props>) => find(tree, (p) => p["aria-label"] === "위치");
const primary = (tree: ReactElement<Props>) => tree.props.primary as { enabled: boolean; run(): Promise<boolean> };
const text = (node: unknown): string =>
  typeof node === "string" ? node : Array.isArray(node) ? node.map(text).join("") : node !== null && typeof node === "object" && "props" in node ? text((node as ReactElement<Props>).props.children) : "";

const calls: unknown[] = [];
let reply: () => Promise<unknown>;

beforeEach(() => {
  H.slots = [];
  calls.length = 0;
  vi.stubGlobal("window", {
    kookabug: {
      app: {
        workspaceCreate: (request: unknown) => {
          calls.push(request);
          return reply();
        },
        pickFolder: () => Promise.resolve(null),
      },
    },
  });
});

function typeLocation(value: string) {
  const input = locationInput(render());
  expect(input).toBeDefined();
  expect(input?.props.readOnly).toBeUndefined();
  (input?.props.onChange as (e: { target: { value: string } }) => void)({ target: { value } });
}

describe("위치 칸 직접 입력 → 만들기", () => {
  test("빈 위치면 만들기가 꺼져 있고, 붙여 넣으면 켜진다", () => {
    expect(primary(render()).enabled).toBe(false);
    typeLocation('  "D:\\Games\\My Projects"  ');
    const tree = render();
    expect(locationInput(tree)?.props.value).toBe('  "D:\\Games\\My Projects"  ');
    expect(primary(tree).enabled).toBe(true);
  });

  test("누르면 정리한 경로로 만들고, 없는 폴더 거부 글이 오류 칸(role=alert)에 보인다", async () => {
    reply = () => Promise.reject(new Error("Error invoking remote method 'kb:app': Error: parent_missing: 위치 폴더가 없어요"));
    typeLocation('  "D:\\Games\\Missing"  ');
    const button = primary(render());
    expect(button.enabled).toBe(true);
    await expect(button.run()).resolves.toBe(false);
    expect(calls).toEqual([{ parent: "D:\\Games\\Missing", name: "my-game", git: true }]);
    const alert = find(render(), (p) => p.role === "alert");
    expect(alert).toBeDefined();
    expect(text(alert)).toBe("위치 폴더가 없어요");
  });

  test("고쳐 입력하면 새 경로로 다시 부른다", async () => {
    reply = () => Promise.reject(new Error("Error invoking remote method 'kb:app': Error: invalid_parent: 위치는 절대 경로여야 해요"));
    typeLocation("games");
    await primary(render()).run();
    expect(text(find(render(), (p) => p.role === "alert"))).toBe("위치는 절대 경로여야 해요");
    reply = () => Promise.resolve({ ok: false });
    typeLocation("E:\\QA");
    await expect(primary(render()).run()).resolves.toBe(false);
    expect(calls.at(-1)).toEqual({ parent: "E:\\QA", name: "my-game", git: true });
    expect(text(find(render(), (p) => p.role === "alert"))).toBe("만든 폴더를 열지 못했어요");
  });
});
