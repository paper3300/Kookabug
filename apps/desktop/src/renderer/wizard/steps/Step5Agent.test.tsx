// 5단계 Agent 저장 회귀 (합치기 검수 review_merge_1 High 3건). 컴포넌트는 그리지 않고 실제 Step5Agent의 콜백을 부른다:
// React 훅만 작은 대역으로 바꾸고(상태 칸·ref·effect), 저장소·RPC는 revision 충돌 검사가 있는 메모리 사용자 설정 파일이다.
// (a) 화면이 읽은 뒤 다른 곳에서 바꾼 프리셋은 저장이 충돌로 거부되고 그 값이 남는다
// (b) read_only 사용자가 only 화면에서 권한을 건드리지 않고 저장하면 read_only 그대로
// (c) 에이전트 둘 중 마지막에 B를 기본으로 고르고 저장하면 다시 읽어도 B
// review_merge_2: (d·e) new·short에서 연결 시험 중 다른 줄을 고르면 앞 결과를 버리고 지금 선택을 시험한다
// (f) 충돌 뒤 다시 읽기가 실패하면 충돌·고른 값이 남는다
// review_merge_3: (g) "다음" 중 줄 잠김, (h) 에이전트 저장 충돌은 다시 읽기 전까지 막힘, (i) 외부 기본 변경을 "다음"이 덮지 않음
import type { ReactElement, ReactNode } from "react";
import { beforeEach, describe, expect, test, vi } from "vitest";

const H = vi.hoisted(() => ({ slots: [] as unknown[], i: 0, effects: [] as (() => void)[] }));

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
  const useRef = (init: unknown) => {
    const i = H.i++;
    if (!(i in H.slots)) H.slots[i] = { current: init };
    return H.slots[i];
  };
  const useEffect = (fn: () => void, deps?: unknown[]) => {
    const i = H.i++;
    const prev = H.slots[i] as unknown[] | undefined;
    if (prev === undefined || deps === undefined || deps.some((d, k) => !Object.is(d, prev[k]))) {
      H.slots[i] = deps ?? [];
      H.effects.push(fn);
    }
  };
  return { ...React, default: React, useState, useRef, useEffect };
});

const rpc = vi.hoisted(() => {
  interface UserFile {
    n: number;
    revision: string;
    agents: { id: string; name: string; command: string; args?: string[] }[];
    default_agent: string | null;
    permissions: Record<string, unknown>;
  }
  const file: UserFile = { n: 1, revision: "rev-1", agents: [], default_agent: null, permissions: {} };
  const sets: { method: string; base: unknown }[] = [];
  /** true면 agents.get·permissions.get이 실패한다 (다시 읽기 실패) */
  /** gates[method]가 있으면 그 RPC는 풀릴 때까지 기다린다 (revision 검사는 풀린 뒤) */
  return { file, sets, candidates: [] as Record<string, unknown>[], failGets: false, gates: {} as Record<string, Promise<void>> };
});

vi.mock("../../rpc/client", async (original) => {
  const mod = await original<typeof import("../../rpc/client")>();
  const { file, sets } = rpc;
  const bump = () => {
    file.n += 1;
    file.revision = `rev-${file.n}`;
  };
  const conflict = () => new mod.RpcError(-32100, "그 사이 바뀌었다", { code: "revision_conflict", revision: file.revision });
  const call = async (method: string, params: Record<string, unknown>): Promise<unknown> => {
    await Promise.resolve();
    const gate = rpc.gates[method];
    if (gate !== undefined) await gate;
    if (rpc.failGets && (method === "agents.get" || method === "permissions.get")) throw new mod.RpcError(-32000, "읽기 실패", {});
    switch (method) {
      case "permissions.get":
        return { principal: {}, tools: [], layers: [{ layer: "user", permissions: structuredClone(file.permissions), revision: file.revision }] };
      case "agents.get":
        return { agents: structuredClone(file.agents), default_agent: file.default_agent, revision: file.revision };
      case "agents.detect":
        return { candidates: structuredClone(rpc.candidates) };
      case "agents.set":
        sets.push({ method, base: params.base_revision });
        if (params.base_revision !== file.revision) throw conflict();
        file.agents = structuredClone(params.agents) as typeof file.agents;
        file.default_agent = params.default_agent as string | null;
        bump();
        return { revision: file.revision };
      case "permissions.set":
        sets.push({ method, base: params.base_revision });
        if (params.base_revision !== file.revision) throw conflict();
        file.permissions = structuredClone(params.permissions) as Record<string, unknown>;
        bump();
        return { revision: file.revision };
      default:
        return {};
    }
  };
  return { ...mod, client: () => ({ call, on: () => () => undefined }) };
});

// 훅은 저장소의 지금 값을 그대로 돌려준다 (구독 없이 다시 부를 때마다 읽는다)
vi.mock("../../agent/agentStore", async (original) => {
  const mod = await original<typeof import("../../agent/agentStore")>();
  const hook = Object.assign((sel: (s: ReturnType<typeof mod.useAgent.getState>) => unknown) => sel(mod.useAgent.getState()), mod.useAgent);
  return { ...mod, useAgent: hook };
});
vi.mock("../wizardStore", async (original) => {
  const mod = await original<typeof import("../wizardStore")>();
  const hook = Object.assign((sel: (s: ReturnType<typeof mod.useWizard.getState>) => unknown) => sel(mod.useWizard.getState()), mod.useWizard);
  return { ...mod, useWizard: hook };
});
vi.mock("../Wizard", () => ({ StepShell: () => null }));
vi.mock("./Step1Project", () => ({ appErrorText: (e: unknown) => String(e) }));
vi.mock("../../store/ui", () => ({ openAgentPanel: vi.fn() }));

const { useAgent, refreshAgents, refreshPermissions, setUserPreset } = await import("../../agent/agentStore");
const { useWizard } = await import("../wizardStore");
const { Step5Agent } = await import("./Step5Agent");
const { ConflictNotice } = await import("../Conflict");

type El = ReactElement<Record<string, unknown>>;

async function flush(): Promise<void> {
  for (let k = 0; k < 20; k++) await new Promise((r) => setTimeout(r, 0));
}

/** 한 번 그린다 (effect는 그린 뒤 바로 부른다) */
function render(): El {
  H.i = 0;
  const el = Step5Agent() as El;
  for (const fx of H.effects.splice(0)) fx();
  return el;
}

/** 그려진 트리의 요소 전부 (StepShell의 right 칸 포함) */
function elements(node: ReactNode): El[] {
  if (Array.isArray(node)) return node.flatMap(elements);
  if (node === null || typeof node !== "object" || !("props" in node)) return [];
  const el = node as El;
  return [el, ...elements(el.props.children as ReactNode), ...elements(el.props.right as ReactNode)];
}

function text(node: ReactNode): string {
  if (Array.isArray(node)) return node.map(text).join("");
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (node !== null && typeof node === "object" && "props" in node) return text((node as El).props.children as ReactNode);
  return "";
}

/** 본문 줄 고르기 (radio onChange) */
function pickRow(id: string): void {
  const row = elements(render()).find((e) => e.props["data-agent"] === id);
  const radio = elements(row?.props.children as ReactNode).find((e) => e.type === "input");
  if (radio === undefined) throw new Error(`줄 없음: ${id}`);
  (radio.props.onChange as () => void)();
}

/** 기본 에이전트로 고르기: 따로 고르는 칸이 있으면 그 칸, 없으면 본문 줄 (고른 에이전트 = 기본 에이전트) */
function pickDefault(id: string): void {
  const picker = elements(render()).find((e) => e.props.part === "pick-default-agent");
  if (picker !== undefined) (picker.props.onPick as (v: string) => void)(id);
  else pickRow(id);
}

function pressPreset(label: string): void {
  const button = elements(render()).find((e) => e.type === "button" && text(e.props.children as ReactNode) === label);
  if (button === undefined) throw new Error(`프리셋 단추 없음: ${label}`);
  (button.props.onClick as () => void)();
}

/** only 모드 "저장" (extra 단추). 꺼져 있으면 false */
async function save(): Promise<boolean> {
  const extra = render().props.extra as { enabled: boolean; run: () => Promise<boolean> };
  if (!extra.enabled) return false;
  const ok = await extra.run();
  await flush();
  return ok;
}

const A = { id: "agent-a", name: "Agent A", command: "a-acp" };
const B = { id: "agent-b", name: "Agent B", command: "b-acp" };

function setup(user: { agents: (typeof A)[]; default_agent: string | null; preset?: string }, mode: "only" | "new" | "short" = "only"): void {
  rpc.failGets = false;
  rpc.gates = {};
  rpc.file.n = 1;
  rpc.file.revision = "rev-1";
  rpc.file.agents = structuredClone(user.agents);
  rpc.file.default_agent = user.default_agent;
  rpc.file.permissions = user.preset === undefined ? {} : { preset: user.preset };
  rpc.sets.length = 0;
  rpc.candidates = [];
  H.slots = [];
  H.effects = [];
  useAgent.setState({ agents: [], agentsRevision: null, defaultAgent: null, agentsLoaded: false, permissions: null, candidates: null, startError: null, userConflict: false, userBase: null, ownDefault: null } as never);
  const p = useWizard.getState().progress;
  useWizard.setState({ agent: null, progress: { ...p, mode, steps: mode === "only" ? [5] : p.steps, step: 5 } });
}

/** 다른 곳(다른 창·사람)이 사용자 설정 파일을 바꾼다 */
function external(change: (f: typeof rpc.file) => void): void {
  change(rpc.file);
  rpc.file.n += 1;
  rpc.file.revision = `rev-${rpc.file.n}`;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("(a) 프리셋 저장은 화면이 읽은 revision 기준", () => {
  test("패널: 읽은 뒤 다른 곳에서 read_only로 바꾸면 full 저장은 충돌, 외부 값이 남는다", async () => {
    setup({ agents: [A], default_agent: A.id, preset: "graph_author" });
    await refreshAgents();
    await refreshPermissions();
    external((f) => (f.permissions = { preset: "read_only", rules: ["kb_run: deny"] }));
    const problem = await setUserPreset("full");
    expect(problem).not.toBeNull();
    expect(rpc.file.permissions).toEqual({ preset: "read_only", rules: ["kb_run: deny"] });
    expect(rpc.sets).toEqual([{ method: "permissions.set", base: "rev-1" }]);
    expect(useAgent.getState().userConflict).toBe(true);
  });

  test("5단계: 화면을 연 뒤 다른 곳에서 바꾸면 저장이 충돌로 끝나지 않고 외부 값이 남는다", async () => {
    setup({ agents: [A], default_agent: A.id, preset: "graph_author" });
    render();
    await flush();
    pickRow(A.id);
    await flush();
    pressPreset("전체");
    external((f) => (f.permissions = { preset: "read_only" }));
    expect((render().props.extra as { enabled: boolean }).enabled).toBe(true);
    expect(await save()).toBe(false);
    expect(rpc.file.permissions).toEqual({ preset: "read_only" });
    // 다시 읽기 전까지 저장 단추는 꺼진다
    expect((render().props.extra as { enabled: boolean }).enabled).toBe(false);
  });

  test("같은 흐름에서 자기가 먼저 쓴 agents 저장의 revision은 이어 받는다 (충돌 아님)", async () => {
    setup({ agents: [A], default_agent: A.id, preset: "graph_author" });
    rpc.candidates = [{ id: B.id, name: B.name, command: B.command, args: [], installed: true, cli_path: null, via: "path", cli: "b", package: null }];
    render();
    await flush();
    // 감지한 B를 고르면 agents.set(더하고 기본으로), 이어서 프리셋을 바꿔 저장하면 permissions.set은 그 응답 revision
    pickRow(B.id);
    await flush();
    pressPreset("전체");
    expect(await save()).toBe(true);
    expect(rpc.sets).toEqual([
      { method: "agents.set", base: "rev-1" },
      { method: "permissions.set", base: "rev-2" },
    ]);
    expect(rpc.file.permissions).toEqual({ preset: "full" });
    expect(rpc.file.default_agent).toBe(B.id);
  });
});

describe("(b) only 화면은 지금 프리셋을 보이고 바꿨을 때만 저장", () => {
  test("read_only 사용자가 권한을 건드리지 않고 저장하면 read_only 그대로", async () => {
    setup({ agents: [A], default_agent: A.id, preset: "read_only" });
    render();
    await flush();
    pickRow(A.id);
    await flush();
    expect(await save()).toBe(true);
    expect(rpc.file.permissions).toEqual({ preset: "read_only" });
  });

  test("새 프로젝트이면서 사용자 프리셋이 없을 때만 curator 추천을 저장한다", async () => {
    setup({ agents: [A], default_agent: A.id }, "new");
    render();
    await flush();
    const primary = render().props.primary as { run: () => Promise<boolean> };
    expect(await primary.run()).toBe(true);
    expect(rpc.file.permissions).toEqual({ preset: "curator" });
  });
});

describe("(c) 고른 에이전트 = 기본 에이전트", () => {
  test("A를 고른 뒤 B를 기본으로 고르고 저장하면 다시 읽어도 B", async () => {
    setup({ agents: [A, B], default_agent: A.id, preset: "graph_author" });
    render();
    await flush();
    pickRow(A.id);
    await flush();
    pickDefault(B.id);
    await flush();
    expect(await save()).toBe(true);
    await refreshAgents();
    expect(useAgent.getState().defaultAgent).toBe(B.id);
    expect(rpc.file.default_agent).toBe(B.id);
  });
});

/** 연결 시험 대역: 부를 때마다 응답을 사람이 끝낼 때까지 기다린다 */
function probeStub(): { calls: string[]; finish: (id: string, ok: boolean) => void } {
  const calls: string[] = [];
  const waiting = new Map<string, ((r: { ok: boolean }) => void)[]>();
  const agentProbe = (id: string) =>
    new Promise<{ ok: boolean }>((resolve) => {
      calls.push(id);
      waiting.set(id, [...(waiting.get(id) ?? []), resolve]);
    });
  (globalThis as { window?: unknown }).window = { kookabug: { app: { agentProbe } } };
  return {
    calls,
    finish: (id, ok) => {
      const list = waiting.get(id) ?? [];
      const resolve = list.shift();
      if (resolve === undefined) throw new Error(`기다리는 시험 없음: ${id}`);
      resolve({ ok });
    },
  };
}

function primary(): { enabled: boolean; run: () => Promise<boolean> } {
  return render().props.primary as { enabled: boolean; run: () => Promise<boolean> };
}

describe.each(["new", "short"] as const)("(d·e) %s 모드: 연결 시험 중 다른 에이전트를 고르면", (mode) => {
  test("앞 시험 결과는 버리고 지금 고른 것을 이어 시험한다, 다시 읽은 기본은 마지막 고른 것", async () => {
    setup({ agents: [A, B], default_agent: A.id, preset: "read_only" }, mode);
    const probe = probeStub();
    render();
    await flush();
    pickRow(B.id);
    await flush();
    expect(probe.calls).toEqual([B.id]);
    // B 시험이 끝나기 전에 A를 고른다
    pickRow(A.id);
    await flush();
    probe.finish(B.id, true);
    await flush();
    // B 성공은 지금 선택(A)의 결과가 아니다: "다음"은 꺼져 있고 A 시험이 이어 시작된다
    expect(primary().enabled).toBe(false);
    expect(probe.calls).toEqual([B.id, A.id]);
    probe.finish(A.id, true);
    await flush();
    expect(primary().enabled).toBe(true);
    expect(await primary().run()).toBe(true);
    await flush();
    await refreshAgents();
    expect(useAgent.getState().defaultAgent).toBe(A.id);
    expect(rpc.file.default_agent).toBe(A.id);
    expect(useWizard.getState().agent).toMatchObject({ id: A.id, probed: true });
  });
});

describe("(f) 충돌 뒤 다시 읽기", () => {
  test("다시 읽기가 실패하면 충돌·고른 값이 남고 저장이 막힌다, 성공하면 풀린다", async () => {
    setup({ agents: [A], default_agent: A.id, preset: "graph_author" });
    render();
    await flush();
    pickRow(A.id);
    await flush();
    pressPreset("전체");
    external((f) => (f.permissions = { preset: "read_only" }));
    expect(await save()).toBe(false);
    expect(useAgent.getState().userConflict).toBe(true);
    const reload = async () => {
      const notice = elements(render()).find((e) => e.type === ConflictNotice);
      if (notice === undefined) throw new Error("충돌 안내 없음");
      (notice.props.onReload as () => void)();
      await flush();
    };

    rpc.failGets = true;
    await reload();
    expect(useAgent.getState().userConflict).toBe(true);
    expect((render().props.extra as { enabled: boolean }).enabled).toBe(false);
    // 사람이 고른 "전체"는 그대로, 읽기 오류 문구가 보인다
    expect(elements(render()).find((e) => e.props["data-part"] === "preset-hint")?.props["data-preset"]).toBe("full");
    expect(elements(render()).some((e) => e.props.role === "alert" && text(e.props.children as ReactNode).includes("다시 읽지 못했어요"))).toBe(true);

    rpc.failGets = false;
    await reload();
    expect(useAgent.getState().userConflict).toBe(false);
    // 다시 읽은 외부 값(read_only)이 보이고 저장이 풀린다
    expect(elements(render()).find((e) => e.props["data-part"] === "preset-hint")?.props["data-preset"]).toBe("read_only");
    expect(await save()).toBe(true);
    expect(rpc.file.permissions).toEqual({ preset: "read_only" });
  });
});

// review_merge_3: 바쁠 때 줄 선택 잠금, 진행 콜백은 확인만, 에이전트 저장 충돌은 다시 읽기 전까지 막는다

/** 이 RPC를 다음 한 번 잡아 둔다. 돌려준 함수로 푼다 */
function gate(method: string): () => void {
  let open!: () => void;
  rpc.gates[method] = new Promise<void>((r) => (open = r));
  return () => {
    delete rpc.gates[method];
    open();
  };
}

function radio(id: string): El | undefined {
  const row = elements(render()).find((e) => e.props["data-agent"] === id);
  return elements(row?.props.children as ReactNode).find((e) => e.type === "input");
}

function selected(): string[] {
  return elements(render())
    .filter((e) => e.props["data-agent"] !== undefined && e.props["data-selected"] === true)
    .map((e) => e.props["data-agent"] as string);
}

async function reloadByNotice(): Promise<void> {
  const notice = elements(render()).find((e) => e.type === ConflictNotice);
  if (notice === undefined) throw new Error("충돌 안내 없음");
  (notice.props.onReload as () => void)();
  await flush();
}

describe.each(["new", "short"] as const)("(g) %s 모드: \"다음\"을 기다리는 동안", (mode) => {
  test("다른 줄을 고를 수 없고, next() 결과·파일 기본·마지막 선택이 일치한다", async () => {
    setup({ agents: [A, B], default_agent: A.id, preset: "read_only" }, mode);
    const probe = probeStub();
    render();
    await flush();
    pickRow(B.id);
    await flush();
    probe.finish(B.id, true);
    await flush();
    // 프리셋을 바꿔 "다음"이 permissions.set을 기다리게 한다
    pressPreset("전체");
    expect(primary().enabled).toBe(true);
    const release = gate("permissions.set");
    const running = primary().run();
    await flush();
    // 잠김: 줄 단추가 꺼져 있고, 눌러도 선택이 바뀌지 않는다
    expect(radio(A.id)?.props.disabled).toBe(true);
    pickRow(A.id);
    await flush();
    expect(selected()).toEqual([B.id]);
    expect(probe.calls).toEqual([B.id]);
    release();
    expect(await running).toBe(true);
    await flush();
    expect(rpc.file.default_agent).toBe(B.id);
    expect(selected()).toEqual([B.id]);
    expect(useWizard.getState().agent).toMatchObject({ id: B.id, probed: true });
    expect(rpc.sets.filter((x) => x.method === "agents.set")).toHaveLength(1);
    // 끝난 뒤에는 다시 고를 수 있다
    expect(radio(A.id)?.props.disabled).toBe(false);
  });
});

describe.each(["new", "short"] as const)("(h) %s 모드: A 저장이 외부 변경과 충돌하면", (mode) => {
  test("충돌이 켜지고 이어 시험이 끝나도 외부 값이 남는다, 다시 읽은 뒤 다시 고르면 진행된다", async () => {
    setup({ agents: [A, B], default_agent: A.id, preset: "read_only" }, mode);
    const probe = probeStub();
    render();
    await flush();
    pickRow(B.id);
    await flush();
    expect(rpc.file.default_agent).toBe(B.id);
    // B 시험 대기 중 A를 고른다. A 저장은 잡아 둔다
    const release = gate("agents.set");
    pickRow(A.id);
    await flush();
    // 그 사이 외부가 기본 지정을 지우고 권한 규칙을 바꾼다
    external((f) => {
      f.default_agent = null;
      f.permissions = { preset: "read_only", rules: ["kb_run: deny"] };
    });
    release();
    await flush();
    expect(useAgent.getState().userConflict).toBe(true);
    expect(rpc.file.default_agent).toBeNull();
    // B 시험이 끝나 이어 시험으로 가도 저장하지 않는다
    probe.finish(B.id, true);
    await flush();
    expect(rpc.file.default_agent).toBeNull();
    expect(rpc.file.permissions).toEqual({ preset: "read_only", rules: ["kb_run: deny"] });
    const writes = rpc.sets.length;
    expect(primary().enabled).toBe(false);
    expect(await primary().run()).toBe(false);
    await flush();
    expect(rpc.sets.length).toBe(writes);
    expect(rpc.file.default_agent).toBeNull();
    // 충돌 중에는 줄을 고를 수 없다
    expect(radio(B.id)?.props.disabled).toBe(true);

    await reloadByNotice();
    expect(useAgent.getState().userConflict).toBe(false);
    // new·short는 고른 것을 비운다
    expect(selected()).toEqual([]);
    pickRow(A.id);
    await flush();
    probe.finish(A.id, true);
    await flush();
    expect(primary().enabled).toBe(true);
    expect(await primary().run()).toBe(true);
    await flush();
    expect(rpc.file.default_agent).toBe(A.id);
    expect(rpc.file.permissions).toEqual({ preset: "read_only", rules: ["kb_run: deny"] });
  });
});

describe.each(["new", "short"] as const)("(i) %s 모드: B 저장·시험 성공 뒤 외부에서 기본을 A로 바꾸면", (mode) => {
  test.each([
    ["저장소를 갱신함", true],
    ["저장소를 갱신하지 않음", false],
  ] as const)("%s: \"다음\"은 파일을 덮지 않고 충돌로 끝나지 않는다", async (_label, refresh) => {
    setup({ agents: [A, B], default_agent: A.id, preset: "read_only" }, mode);
    const probe = probeStub();
    render();
    await flush();
    pickRow(B.id);
    await flush();
    probe.finish(B.id, true);
    await flush();
    expect(primary().enabled).toBe(true);
    external((f) => (f.default_agent = A.id));
    // 재연결(agentConnected) 같은 다른 경로의 읽기
    if (refresh) await refreshAgents();
    const writes = rpc.sets.length;
    expect(await primary().run()).toBe(false);
    await flush();
    expect(rpc.sets.length).toBe(writes);
    expect(rpc.file.default_agent).toBe(A.id);
    expect(useAgent.getState().userConflict).toBe(true);
    expect(elements(render()).some((e) => e.type === ConflictNotice)).toBe(true);
  });
});
