// 값 → 캔버스 사상 (M2 계획 T8 완료 기준 mapping.test.ts)
import fs from "node:fs";
import path from "node:path";
import { describe, expect, test } from "vitest";
import {
  BACK_EDGE_CLASS,
  BACK_EDGE_Z,
  dataEdgeId,
  EXEC_IN,
  execEdgeId,
  exitHandle,
  groupNodeId,
  indexNodeTypes,
  inputHandle,
  outputHandle,
  toFlow,
  type GroupNodeData,
  type KbFlowEdge,
  type KbNodeData,
  type MappingInput,
} from "./mapping";
import type { GraphValue, NodeShapes } from "./model";

const REPO = path.resolve(import.meta.dirname, "..", "..", "..", "..", "..");
const CORE_SCHEMA = path.join(REPO, "python", "kookabug_nodes", "src", "kookabug_nodes", "kookabug.schema.json");
const CORPUS = JSON.parse(fs.readFileSync(path.join(REPO, "fixtures", "graph-corpus", "corpus.json"), "utf8")) as {
  files: string[];
};

const types = indexNodeTypes([JSON.parse(fs.readFileSync(CORE_SCHEMA, "utf8").replace(/^﻿/, ""))]);

function readCorpus(rel: string): GraphValue {
  return JSON.parse(fs.readFileSync(path.join(REPO, rel), "utf8").replace(/^﻿/, "")) as GraphValue;
}

function input(value: GraphValue, extra: Partial<MappingInput> = {}): MappingInput {
  return {
    path: "tests/a.graph.json",
    value,
    shapes: {},
    types,
    diagnostics: [],
    view: { expanded: new Set(), selected: new Set() },
    ...extra,
  };
}

const kb = (flow: ReturnType<typeof toFlow>, id: string) => flow.nodes.find((n) => n.id === id)!.data as KbNodeData;
/** 줄임 표기 "x:노드:출구"·"d:노드:핀" (값 안 경로 없음) → 연결선 ID */
const E = (short: string) => {
  const [kind, node, name] = short.split(":");
  return kind === "x" ? execEdgeId(node, name) : dataEdgeId(node, name, []);
};
const edge = (flow: ReturnType<typeof toFlow>, short: string) => flow.edges.find((e) => e.id === E(short)) as KbFlowEdge;

/** 키를 정렬한 문자열 (값 비교용, 자기 속성만) */
function sorted(v: unknown): string {
  if (Array.isArray(v)) return `[${v.map(sorted).join(",")}]`;
  if (typeof v === "object" && v !== null) {
    const o = v as Record<string, unknown>;
    return `{${Object.keys(o)
      .sort()
      .map((k) => `${JSON.stringify(k)}:${sorted(o[k])}`)
      .join(",")}}`;
  }
  return JSON.stringify(v);
}

function deepFreeze<T>(v: T): T {
  if (typeof v === "object" && v !== null) {
    for (const k of Object.keys(v)) deepFreeze((v as Record<string, unknown>)[k]);
    Object.freeze(v);
  }
  return v;
}

const linear: GraphValue = {
  format: "kookabug.graph/0",
  kind: "test",
  nodes: {
    n_entry: { type: "core.graph.entry", version: 1, next: { start: "n_wait" } },
    n_wait: {
      type: "core.image.wait",
      version: 1,
      in: { target: { $target: "targets/title/start_button.target.json" }, timeout_ms: 60000 },
      next: { found: "n_click", timeout: "n_fail" },
    },
    n_click: { type: "core.input.click", version: 1, in: { match: { $link: "n_wait.match" } }, next: { done: "n_pass" } },
    n_pass: { type: "core.test.pass", version: 1 },
    n_fail: { type: "core.test.fail", version: 1 },
  },
};

const shapes: NodeShapes = {
  n_wait: {
    unknown: false,
    inputs: [
      { name: "target", type: "target", nullable: false, optional: false, required: true },
      { name: "timeout_ms", type: "int", nullable: false, optional: false, required: false, default: 10000 },
    ],
    outputs: [{ name: "match", type: "match", nullable: false }],
    exits: [
      { name: "found", kind: "ok", outputs: ["match"] },
      { name: "timeout", kind: "fail", outputs: [] },
    ],
  },
};

describe("흐름·데이터 연결", () => {
  test("test_exec_edges_from_next", () => {
    const flow = toFlow(input(linear, { shapes }));
    const execs = flow.edges.filter((e) => e.data?.kind === "exec").map((e) => e.id);
    expect(execs.sort()).toEqual(
      ["x:n_click:done", "x:n_entry:start", "x:n_wait:found", "x:n_wait:timeout"].map(E).sort(),
    );
    const found = edge(flow, "x:n_wait:found");
    expect(found).toMatchObject({ source: "n_wait", target: "n_click", sourceHandle: exitHandle("found"), targetHandle: EXEC_IN });
    expect(found.data?.tone).toBe("exec");
    // fail 출구는 주황 점선
    expect(edge(flow, "x:n_wait:timeout").data?.tone).toBe("fail");
    // 출구 줄: ok 출구, 출력, fail 출구 순
    const rows = kb(flow, "n_wait").rows.map((r) => r.right?.label ?? null);
    expect(rows).toEqual(["found", "match", "timeout"]);
    // 없는 노드를 가리키는 next는 그리지 않는다 (검증 오류로 나온다)
    const broken = structuredClone(linear) as { nodes: Record<string, { next?: Record<string, string> }> };
    broken.nodes.n_click.next = { done: "n_nowhere" };
    expect(toFlow(input(broken as GraphValue)).edges.some((e) => e.id === E("x:n_click:done"))).toBe(false);
  });

  test("test_data_edges_from_links_including_nested", () => {
    const flow = toFlow(input(linear, { shapes }));
    const match = edge(flow, "d:n_click:match");
    expect(match).toMatchObject({
      source: "n_wait",
      target: "n_click",
      sourceHandle: outputHandle("match"),
      targetHandle: inputHandle("match"),
    });
    expect(match.data).toEqual({ kind: "data", tone: "region", where: "" });

    const special = toFlow(input(readCorpus("fixtures/graph-corpus/special-values.graph.json")));
    const data = special.edges.filter((e) => e.data?.kind === "data");
    // 배열·중첩 배열·객체 안쪽 $link. $literal 안의 $link는 연결이 아니다
    expect(data.map((e) => [e.id, e.source, e.data?.where]).sort()).toEqual(
      [
        [dataEdgeId("n_sink", "list", [0]), "n_a", "[0]"],
        [dataEdgeId("n_sink", "list", [2, 0]), "n_b", "[2][0]"],
        [dataEdgeId("n_sink", "obj", ["k"]), "n_a", ".k"],
      ].sort(),
    );
    // 같은 핀으로 들어오는 연결 셋이 그 핀 손잡이로 간다
    expect(new Set(data.map((e) => e.targetHandle))).toEqual(new Set([inputHandle("list"), inputHandle("obj")]));
  });

  test("값 안 경로의 키에 마침표·대괄호가 있어도 연결선 ID가 겹치지 않는다 (T8 검수 1차)", () => {
    const value: GraphValue = {
      nodes: {
        a: { type: "core.var.get", version: 1, in: { name: "a" } },
        b: { type: "core.var.get", version: 1, in: { name: "b" } },
        sink: {
          type: "core.var.set",
          version: 1,
          in: {
            name: "result",
            value: {
              "a.b": { $link: "a.value" },
              a: { b: { $link: "b.value" } },
              "x[0]": { $link: "a.value" },
              x: [{ $link: "b.value" }],
            },
          },
        },
      },
    };
    const data = toFlow(input(value)).edges.filter((e) => e.data?.kind === "data");
    expect(data).toHaveLength(4);
    expect(new Set(data.map((e) => e.id)).size).toBe(4);
    // 각 연결의 출발점이 제자리다 (ID로 다른 연결을 덮지 않는다)
    const by = new Map(data.map((e) => [e.id, e.source]));
    expect(by.get(dataEdgeId("sink", "value", ["a.b"]))).toBe("a");
    expect(by.get(dataEdgeId("sink", "value", ["a", "b"]))).toBe("b");
    expect(by.get(dataEdgeId("sink", "value", ["x[0]"]))).toBe("a");
    expect(by.get(dataEdgeId("sink", "value", ["x", 0]))).toBe("b");
    // 원소 번호와 같은 글자의 키도 다르다
    expect(dataEdgeId("n", "p", [0])).not.toBe(dataEdgeId("n", "p", ["0"]));
  });

  test("뒤로 가는 연결은 노드 위 층에 그린다", () => {
    const value: GraphValue = {
      layout: { nodes: { n_a: { x: 400, y: 0 }, n_b: { x: 0, y: 200 } } },
      nodes: {
        n_a: { type: "core.flow.delay", version: 1, in: { ms: 1 }, next: { done: "n_b" } },
        n_b: { type: "core.flow.delay", version: 1, in: { ms: 1 }, next: { done: "n_c" } },
        n_c: { type: "core.flow.delay", version: 1, in: { ms: 1 } },
      },
    };
    const flow = toFlow(input(value));
    expect(edge(flow, "x:n_a:done")).toMatchObject({ zIndex: BACK_EDGE_Z, interactionWidth: 0, className: BACK_EDGE_CLASS });
    // 자동 배치로 오른쪽에 놓인 노드로 가는 연결은 보통 층
    expect(edge(flow, "x:n_b:done").zIndex).toBeUndefined();
    expect(edge(flow, "x:n_b:done").className).toBeUndefined();
  });

  test("test_unknown_node_pins_from_json_keys", () => {
    const value = readCorpus("fixtures/graph-corpus/unknown-node.graph.json");
    const flow = toFlow(input(value));
    const magic = kb(flow, "n_magic");
    expect(magic.unknown).toBe(true);
    expect(magic.status).toEqual({ text: "모르는 노드", tone: "muted" });
    expect(magic.title).toBe("acme.vision.magic");
    const left = magic.rows.map((r) => r.left?.handle).filter(Boolean);
    const right = magic.rows.map((r) => r.right?.handle).filter(Boolean);
    // 핀 = in 키, 출구 = next 키, 출력 = 다른 노드가 $link로 읽는 이름
    expect(left).toEqual([EXEC_IN, inputHandle("region"), inputHandle("target")]);
    expect(right).toEqual([exitHandle("found"), exitHandle("missing"), outputHandle("label"), outputHandle("reason")]);
    // daemon이 준 대체 모양(unknown)이 있어도 같다
    const daemonShape: NodeShapes = {
      n_magic: {
        unknown: true,
        inputs: [
          { name: "region", type: "any", nullable: true, optional: true, required: false },
          { name: "target", type: "any", nullable: true, optional: true, required: false },
        ],
        outputs: [
          { name: "label", type: "any", nullable: true },
          { name: "reason", type: "any", nullable: true },
        ],
        exits: [
          { name: "found", kind: "ok", outputs: [] },
          { name: "missing", kind: "ok", outputs: [] },
        ],
      },
    };
    const withShape = kb(toFlow(input(value, { shapes: daemonShape })), "n_magic");
    expect(withShape.rows).toEqual(magic.rows);
    // 연결은 다 그린다
    expect(flow.edges.map((e) => e.id).sort()).toEqual(
      ["d:n_fail:reason", "d:n_log:text", "x:n_entry:start", "x:n_log:done", "x:n_magic:found", "x:n_magic:missing"]
        .map(E)
        .sort(),
    );
  });

  test("모양에 없는 핀·출구도 연결이 있으면 줄을 더한다", () => {
    const value = structuredClone(linear) as { nodes: Record<string, Record<string, unknown>> };
    value.nodes.n_click.in = { bogus: { $link: "n_wait.nothing" } };
    value.nodes.n_wait.next = { found: "n_click", timeout: "n_fail", extra_exit: "n_pass" };
    const flow = toFlow(input(value as GraphValue, { shapes }));
    const wait = kb(flow, "n_wait");
    expect(wait.rows.some((r) => r.right?.handle === exitHandle("extra_exit") && r.right.extra)).toBe(true);
    expect(wait.rows.some((r) => r.right?.handle === outputHandle("nothing") && r.right.extra)).toBe(true);
    expect(kb(flow, "n_click").rows.some((r) => r.left?.handle === inputHandle("bogus") && r.left.extra)).toBe(true);
  });

  test("daemon 모양이 오기 전에는 노드 스키마의 정적 모양 (동적 출구는 config 순서)", () => {
    const value: GraphValue = {
      nodes: {
        n_any: {
          type: "core.image.wait_any",
          version: 1,
          config: { exits: ["maintenance", "login"] },
          in: { targets: { login: { $target: "targets/a.target.json" } } },
        },
        n_old: { type: "core.image.wait", version: 99, in: { target: { $target: "targets/a.target.json" } } },
      },
    };
    const flow = toFlow(input(value));
    const any = kb(flow, "n_any");
    expect(any.unknown).toBe(false);
    expect(any.rows.map((r) => r.right?.label ?? null)).toEqual(["maintenance", "login", "match", "timeout"]);
    expect(any.rows.find((r) => r.right?.label === "timeout")?.right?.tone).toBe("fail");
    // targets(필수)는 줄, timeout_ms(기본값 있음)는 줄이 아니다
    expect(any.rows.map((r) => r.left?.handle ?? null)).toEqual([EXEC_IN, inputHandle("targets"), null, null]);
    // 판이 다른 노드는 모르는 노드 (daemon과 같은 판정)
    expect(kb(flow, "n_old").unknown).toBe(true);
  });

  test("판단 노드: 선택지마다 출구 + unsure(fail), 머리에 비결정 배지 (M5 B4)", () => {
    const value: GraphValue = {
      nodes: {
        n_cli: {
          type: "core.agent.cli_judge",
          version: 1,
          config: { choices: ["maintenance", "event"] },
          in: { prompt: "이 팝업은?" },
        },
        n_api: {
          type: "core.agent.api_judge",
          version: 1,
          config: { choices: ["yes"], provider: "openai_compatible" },
          in: { prompt: "?", model: "m", api_key: { $secret: "model.key" } },
        },
        n_wait: { type: "core.image.wait", version: 1, in: { target: { $target: "targets/a.target.json" } } },
      },
    };
    const flow = toFlow(input(value));
    const cli = kb(flow, "n_cli");
    // 성공 출구(선택지 순서) → 출력 → 실패 출구 (wait_any와 같은 배치)
    expect(cli.rows.map((r) => r.right?.label ?? null)).toEqual(["maintenance", "event", "answer", "reason", "unsure"]);
    expect(cli.rows.find((r) => r.right?.label === "unsure")?.right?.tone).toBe("fail");
    expect(cli.head).toBe("purple");
    expect(cli.status).toEqual({ text: "비결정", tone: "agent" });
    const api = kb(flow, "n_api").rows.map((r) => r.right?.label ?? null);
    expect([api[0], api.at(-1)]).toEqual(["yes", "unsure"]);
    expect(kb(flow, "n_api").status?.text).toBe("비결정");
    // 결정적인 노드에는 배지가 없다
    expect(kb(flow, "n_wait").status).toBeNull();
  });

  test("흐름 입력: 시작·순수 노드에는 없다", () => {
    const flow = toFlow(input(linear, { shapes }));
    expect(kb(flow, "n_entry").rows[0].left).toBeNull();
    expect(kb(flow, "n_wait").rows[0].left?.handle).toBe(EXEC_IN);
    const pure: GraphValue = { nodes: { n_get: { type: "core.var.get", version: 1, in: { name: "x" } } } };
    expect(kb(toFlow(input(pure)), "n_get").rows.some((r) => r.left?.handle === EXEC_IN)).toBe(false);
  });
});

describe("접힌 그룹·주석", () => {
  const value = readCorpus("fixtures/graph-corpus/groups-comments.graph.json");

  test("test_collapsed_group_hides_members", () => {
    const flow = toFlow(input(value));
    const ids = flow.nodes.map((n) => n.id);
    expect(ids).toContain(groupNodeId("g_main"));
    expect(ids).not.toContain("n_log");
    expect(ids).not.toContain("n_pass");
    const group = flow.nodes.find((n) => n.id === groupNodeId("g_main"))!;
    expect(group.position).toEqual({ x: 300, y: 40 });
    expect(group.data as GroupNodeData).toMatchObject({ title: "본문", count: 2, expanded: false });
    // 밖에서 들어오는 연결은 그룹으로, 그룹 안쪽 연결은 숨긴다
    expect(edge(flow, "x:n_entry:start")).toMatchObject({ target: groupNodeId("g_main"), targetHandle: "g:in" });
    expect(flow.edges.some((e) => e.id === E("x:n_log:done"))).toBe(false);
    // 보기 상태로 펼치면 구성원이 보이고 연결은 제자리로
    const open = toFlow(input(value, { view: { expanded: new Set(["g_main"]), selected: new Set() } }));
    expect(open.nodes.map((n) => n.id)).toEqual(expect.arrayContaining(["n_log", "n_pass", groupNodeId("g_main")]));
    expect(edge(open, "x:n_entry:start")).toMatchObject({ target: "n_log", targetHandle: EXEC_IN });
    expect(edge(open, "x:n_log:done")).toMatchObject({ source: "n_log", target: "n_pass" });
  });

  test("test_comments_rendered", () => {
    const flow = toFlow(input(value));
    const comment = flow.nodes.find((n) => n.type === "kbComment")!;
    expect(comment).toMatchObject({
      id: "comment:c_note",
      position: { x: -20, y: -40 },
      width: 640,
      height: 160,
      zIndex: -1,
      selectable: false,
      data: { id: "c_note", text: "메모: 접힌 그룹" },
    });
  });
});

describe("열기는 값을 바꾸지 않는다 (2.6)", () => {
  test.each(CORPUS.files)("test_open_does_not_change_value[%s]", (rel) => {
    const value = readCorpus(rel);
    const before = sorted(value);
    // 얼려 두면 사상이 값을 고치려 할 때 던진다
    const flow = toFlow(input(deepFreeze(value)));
    expect(sorted(value)).toBe(before);
    expect(sorted(readCorpus(rel))).toBe(before);
    // 노드마다 그린다 (접힌 그룹 구성원은 그룹으로)
    const nodes = Object.keys((value.nodes ?? {}) as object);
    for (const id of nodes) {
      expect(flow.nodes.some((n) => n.id === id) || flow.hiddenIn.has(id), id).toBe(true);
    }
  });

  test("열 때 정한 보기용 자리(view.auto)는 다른 노드를 더해도 그대로다 (T9)", () => {
    const first = toFlow(input(linear));
    const auto = new Map(first.nodes.map((n) => [n.id, n.position]));
    // 노드 하나에 좌표가 생기면 자동 배치는 그 아래로 옮겨 가지만, 정해 둔 자리가 있으면 그대로
    const placed: GraphValue = {
      ...linear,
      nodes: { ...(linear.nodes as object), n_new: { type: "core.flow.delay", version: 1 } },
      layout: { nodes: { n_new: { x: 900, y: -500 } } },
    };
    const moved = toFlow(input(placed));
    expect(moved.nodes.find((n) => n.id === "n_entry")!.position).not.toEqual(auto.get("n_entry"));
    const stable = toFlow(input(placed, { view: { expanded: new Set(), selected: new Set(), auto } }));
    for (const [id, p] of auto) expect(stable.nodes.find((n) => n.id === id)!.position, id).toEqual(p);
    expect(stable.nodes.find((n) => n.id === "n_new")!.position).toEqual({ x: 900, y: -500 });
  });

  test("좌표 없는 노드는 보기용으로만 배치한다", () => {
    const value = deepFreeze(structuredClone(linear));
    const flow = toFlow(input(value));
    const positions = new Set(flow.nodes.map((n) => `${n.position.x},${n.position.y}`));
    expect(positions.size).toBe(flow.nodes.length);
    expect(Object.hasOwn(value, "layout")).toBe(false);
  });
});

describe("노드 표시", () => {
  test("검증 진단이 노드 머리·설명 줄로", () => {
    const diagnostics = [
      { severity: "error" as const, code: "target_missing", message: "대상 파일이 없다", file: "tests/a.graph.json", node: "n_wait", pointer: "/nodes/n_wait/in/target" },
      { severity: "warning" as const, code: "x", message: "경고", file: null, node: null, pointer: "/nodes/n_click/in/match" },
      { severity: "error" as const, code: "y", message: "다른 파일", file: "subgraphs/b.graph.json", node: "n_click", pointer: null },
    ];
    const flow = toFlow(input(linear, { shapes, diagnostics }));
    expect(kb(flow, "n_wait")).toMatchObject({
      head: "error",
      errors: 1,
      status: { text: "✕ 오류", tone: "error" },
      note: { text: "대상 파일이 없다", tone: "error" },
    });
    // file 없는 진단은 이 문서의 것, 다른 파일의 진단은 이 노드가 아니다
    expect(kb(flow, "n_click")).toMatchObject({ head: "warn", errors: 0, warnings: 1, status: { tone: "warn" } });
  });

  test("머리 색은 분류, 설명 줄은 주요 입력", () => {
    const flow = toFlow(input(linear, { shapes }));
    const wait = kb(flow, "n_wait");
    expect(wait.head).toBe("green");
    expect(wait.title).toBe("이미지 대기");
    expect(wait.note).toEqual({ text: '"start_button" · timeout_ms 60000', tone: "plain" });
    expect(kb(flow, "n_entry").head).toBe("neutral");
  });
});
