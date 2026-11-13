// UX6: 고른 것의 정보·동작은 모든 경우 오른쪽 속성 탭 — RUN 스텝, 보고함 작업, 녹화 스텝, REC 기댓값, target 영역,
// 그래프 노드 마지막 실행 결과. 고르면 접힌 창을 펴고 속성 탭으로, 고른 것 없으면 안내, 탭을 바꾸면 그 탭의 선택, 폭
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, test, vi } from "vitest";

// 속성 탭이 그래프 속성(플러그인 위젯 → 테마 저장소)까지 불러온다: 테마는 window 없이 대역으로
vi.mock("../store/theme", async () => {
  const { create } = await import("zustand");
  return { useTheme: create(() => ({ theme: "dark", mode: "system", setMode: async () => {} })) };
});
import { EMPTY_HISTORY } from "../graph/history";
import { RecorderSidebar } from "../recorder/RecorderSidebar";
import { pickRecStep } from "../recorder/RecorderSidebar";
import { RecTab } from "../recorder/RecTab";
import type { RecorderStep } from "../recorder/labels";
import {
  applyExpected,
  draftTicket,
  fillExpectedDraft,
  refreshState,
  replaceStepFromServer,
  resetRecorder,
  setExpectedDraft,
  useRecorder,
} from "../recorder/recorderStore";
import { pickReport, ReportsTab } from "../reports/ReportsTab";
import { REPORTS_TAB_PATH, useReports, type Report, type Row } from "../reports/reportsStore";
import { index, step } from "../runs/fixtures.testutil";
import { useRunIndex, type RunViewState, type StepDetail, type StepNode } from "../runs/runIndexStore";
import { RunTab } from "../runs/RunTab";
import { pickRunStep } from "../runs/Timeline";
import { useDocuments, type GraphDoc } from "../store/documents";
import { REC_TAB_PATH, runTabPath, useTabs, type EditorTab } from "../store/tabs";
import { inspectorWidthOf, layoutOf, parseLayout, setInspectorWidth, showProps, useUi } from "../store/ui";
import { useWorkspace } from "../store/workspace";
import { useTargets, type TargetDoc } from "../target/targetStore";
import { TargetEditorBody } from "../target/TargetEditor";
import { fileTargetAdapter } from "../target/adapter";
import { newSpec } from "../target/spec";
import { clampWidth } from "./Resizer";
import { RIGHT_MAX_FRACTION, RightPanel } from "./RightPanel";

(globalThis as unknown as { kookabug: unknown }).kookabug = {
  rpc: () => new Promise(() => {}),
  on: () => () => {},
  app: {},
};

// renderToStaticMarkup은 zustand 훅에 서버 스냅샷(처음 상태 객체)을 준다: 그리기 전에 지금 상태를 그 객체에 옮긴다
const STORES = [useWorkspace, useUi, useTabs, useRunIndex, useReports, useRecorder, useTargets, useDocuments] as {
  getState(): object;
  getInitialState(): object;
}[];

function render(node: React.ReactElement): string {
  for (const store of STORES) Object.assign(store.getInitialState(), store.getState());
  return renderToStaticMarkup(node);
}

const RUN = "ab12cd34";

function tab(over: Partial<EditorTab> & Pick<EditorTab, "path" | "kind">): EditorTab {
  return { graphKind: null, title: over.path, ...over };
}

function setTabs(tabs: EditorTab[], active: string): void {
  useTabs.setState({ tabs, active });
}

/** 접힌 창·에이전트 탭에서 시작 */
function collapse(): void {
  useUi.setState({ inspectorOpen: false, rightTab: "agent" });
}

function panel(): string {
  return render(<RightPanel />);
}

function openProps(): void {
  useUi.setState({ inspectorOpen: true, rightTab: "props" });
}

function detail(s: StepNode): StepDetail {
  return {
    run_dir: "runs/r",
    step: s,
    ocr_text: null,
    thumbnail: null,
    events: [
      { event: "step.start", run: RUN, seq: 1, t: s.t_start, step: s.step, node: s.node, parent: null, path: s.path, attempt: 1 },
      {
        event: "step.end",
        run: RUN,
        seq: 2,
        t: s.t_start,
        step: s.step,
        attempt: 1,
        status: "fail",
        exit: "timeout",
        duration_ms: 1400,
        outputs: {},
        evidence: {
          first: "steps/s1_first.png",
          first_at_ms: 0,
          mid: null,
          mid_missing: "no_sample_near_mid",
          last: "steps/s1_fail.png",
          last_at_ms: 1400,
          target: "targets/a.target.json",
          threshold: 0.8,
          candidates: [{ rect: [10, 20, 30, 40], score: 0.41, scale: 1 }],
        },
        artifacts: ["steps/s1_first.png", "steps/s1_fail.png"],
      },
    ] as StepDetail["events"],
  };
}

function runView(over: Partial<RunViewState>): RunViewState {
  return {
    runId: RUN,
    instance: 1,
    status: "ready",
    error: null,
    index: null,
    pages: new Map(),
    expanded: new Set(),
    iteration: new Map(),
    selected: null,
    reveal: null,
    details: new Map(),
    nodes: new Map(),
    testTitle: null,
    view: "timeline",
    runJson: null,
    jumped: true,
    media: "shots",
    pinned: [],
    baseline: null,
    compare: null,
    notice: null,
    ...over,
  };
}

beforeEach(() => {
  useWorkspace.setState({ root: "D:/ws" });
  useUi.setState({ inspectorOpen: true, rightTab: "props", inspectorWidth: null, inspectorWidths: {} });
});

describe("RUN 스텝 상세 → 속성 탭", () => {
  const s1 = step("s1", { status: "fail", exit: "timeout", evidence: true });
  const s2 = step("s2");

  test("타임라인은 RUN 탭에, 고른 스텝의 증거는 속성 탭에. 고르면 접힌 창을 편다", () => {
    useRunIndex.setState({ runs: new Map([[RUN, runView({ index: index([s1, s2]) })]]) });
    setTabs([tab({ path: runTabPath(RUN), kind: "run", runId: RUN })], runTabPath(RUN));
    // 고른 것 없음 → 안내
    expect(panel()).toContain('data-part="run-props-empty"');
    collapse();
    pickRunStep(RUN, "s1");
    expect(useUi.getState()).toMatchObject({ inspectorOpen: true, rightTab: "props" });
    const v = useRunIndex.getState().runs.get(RUN)!;
    useRunIndex.setState({ runs: new Map([[RUN, { ...v, details: new Map([["s1", detail(s1)]]) }]]) });
    const html = panel();
    expect(html).toContain('data-part="run-props"');
    expect(html).toContain('data-part="evidence"');
    expect(html).toContain('data-part="shot-zoom"'); // 크게 보기
    expect(html).toContain('data-part="candidates"');
    expect(html).toContain('data-part="view-in-graph"');
    // RUN 탭 본문은 타임라인만
    const body = render(<RunTab runId={RUN} />);
    expect(body).toContain('data-part="timeline-row"');
    expect(body).not.toContain('data-part="evidence"');
  });
});

describe("보고함 작업 상세 → 속성 탭", () => {
  const row: Row = { job: "j1", playbook: "init", state: "done", startedAt: "2026-11-13T01:00:00Z", groups: 1, undecided: 1, hasReport: true, used: null };
  const report: Report = {
    job: "j1",
    playbook: "init",
    state: "done",
    groups: [{ key: "g1", cause: "c", title: "묶음 하나", items: [{ kind: "working_only", detail: "작업 중" }], decision: null }],
  } as Report;

  test("보고함 탭은 목록만, 고른 작업의 묶음·수락은 속성 탭에", () => {
    useReports.setState({ rows: [row], loaded: true, selected: null, detail: null });
    setTabs([tab({ path: REPORTS_TAB_PATH, kind: "reports" })], REPORTS_TAB_PATH);
    expect(panel()).toContain('data-part="report-props-empty"');
    collapse();
    void pickReport("j1");
    expect(useUi.getState()).toMatchObject({ inspectorOpen: true, rightTab: "props" });
    expect(useReports.getState().selected).toBe("j1");
    useReports.setState({ detail: report });
    const html = panel();
    expect(html).toContain('data-part="report-props"');
    expect(html).toContain('data-part="report-detail"');
    expect(html).toContain('data-part="accept"');
    const body = render(<ReportsTab />);
    expect(body).toContain('data-part="report-list"');
    expect(body).not.toContain('data-part="report-detail"');
    expect(body).not.toContain('data-part="accept"');
  });
});

function recStep(over: Partial<RecorderStep> & Pick<RecorderStep, "step" | "kind">): RecorderStep {
  return { badges: [], needs_review: [], node: { title: "", type: "" }, t_ms: 0, ...over } as RecorderStep;
}

describe("녹화 스텝 → 속성 탭", () => {
  const text = recStep({ step: "s1", kind: "text", t_ms: 1100, text_state: "secret", text_len: 6, node: { title: "비밀값 입력", type: "core.input.type_text" } });
  const review = recStep({ step: "s2", kind: "click", needs_review: ["same_shape"] as never, node: { title: "클릭", type: "core.input.click" } });
  const check = recStep({ step: "s3", kind: "check_text", equals: "100", node: { title: "값 확인", type: "core.assert.text" } } as never);

  test("행을 고르면 REC 탭과 속성 탭: 비밀값/일반 전환·남기기·지우기, 행 안에는 펼치지 않는다", () => {
    useRecorder.setState({
      steps: [text, review, check],
      selected: null,
      checkMode: null,
      state: { state: "stopped", owned: true, window: { title: "게임" } } as never,
    });
    setTabs([tab({ path: REC_TAB_PATH, kind: "rec" })], REC_TAB_PATH);
    expect(panel()).toContain('data-part="rec-props-empty"');
    collapse();
    useTabs.setState({ tabs: [], active: null });
    pickRecStep("s1", "게임");
    expect(useTabs.getState().active).toBe(REC_TAB_PATH);
    expect(useUi.getState()).toMatchObject({ inspectorOpen: true, rightTab: "props" });
    let html = panel();
    expect(html).toContain('data-part="rec-props"');
    expect(html).toContain('data-part="rec-mark-ordinary"');
    // 사이드바 행 안에는 동작이 없다
    const side = render(<RecorderSidebar />);
    expect(side).toContain('data-part="rec-step"');
    expect(side).not.toContain("rec-mark-ordinary");
    expect(side).not.toContain("그대로 남기기");

    pickRecStep("s2", "게임");
    html = panel();
    expect(html).toContain('data-part="rec-keep"');
    expect(html).toContain('data-part="rec-delete"');
  });

  test("값 확인 스텝의 기댓값은 속성 탭에, REC 탭에는 없다", () => {
    useRecorder.setState({ steps: [text, review, check], selected: "s3", checkMode: null });
    setTabs([tab({ path: REC_TAB_PATH, kind: "rec" })], REC_TAB_PATH);
    openProps();
    expect(panel()).toContain('data-part="rec-expected"');
    expect(render(<RecTab />)).not.toContain('data-part="rec-expected"');
  });

  test("적용 안 한 기댓값 초안은 에이전트 탭·접기를 오가도 남고, 적용·삭제·세션 끝에서 지워진다 (검수 H2)", async () => {
    const session = { state: "stopped", owned: true, session: "rs1", window: { title: "게임" } } as never;
    useRecorder.setState({ steps: [text, review, check], selected: "s3", checkMode: null, state: session, expectedDrafts: {} });
    setTabs([tab({ path: REC_TAB_PATH, kind: "rec" })], REC_TAB_PATH);
    openProps();
    expect(panel()).toMatch(/aria-label="기댓값"[^>]*value="100"/);
    setExpectedDraft("s3", "고친 값"); // 입력 칸 onChange
    useUi.setState({ rightTab: "agent" });
    expect(panel()).not.toContain('data-part="rec-expected"');
    useUi.setState({ inspectorOpen: false });
    panel();
    useUi.setState({ inspectorOpen: true, rightTab: "props" });
    expect(panel()).toMatch(/aria-label="기댓값"[^>]*value="고친 값"/);

    // 적용 성공 → 초안 지움 (거부면 남는다)
    const bridge = (globalThis as unknown as { kookabug: { rpc: (m: string, p: unknown) => Promise<unknown> } }).kookabug;
    const before = bridge.rpc;
    bridge.rpc = async (method) => {
      if (method !== "recorder.step.update") throw new Error(method);
      return { step: { ...check, equals: "고친 값" }, rev: 2 };
    };
    try {
      expect(await applyExpected("s3", "고친 값")).toBe(true);
    } finally {
      bridge.rpc = before;
    }
    expect(useRecorder.getState().expectedDrafts).toEqual({});
    expect(panel()).toMatch(/aria-label="기댓값"[^>]*value="고친 값"/);

    // 스텝 삭제 → 그 스텝 초안 지움
    setExpectedDraft("s3", "또 고침");
    replaceStepFromServer("s3", null, 3);
    expect(useRecorder.getState().expectedDrafts).toEqual({});

    // 세션이 끝나면 지움
    useRecorder.setState({ steps: [text, check], state: session });
    setExpectedDraft("s3", "남은 글");
    useRecorder.setState({ state: null });
    resetRecorder();
    expect(useRecorder.getState().expectedDrafts).toEqual({});
  });

  test("늦은 글자 읽기·적용 응답은 다른 녹화의 같은 ID 초안을 바꾸지 않고, 요청 중 고친 초안은 남긴다 (검수 2 High)", async () => {
    const bridge = (globalThis as unknown as { kookabug: { rpc: (m: string, p: unknown) => Promise<unknown> } }).kookabug;
    const before = bridge.rpc;
    const stateA = { state: "stopped", owned: true, session: "A" };
    const stateB = { state: "stopped", owned: true, session: "B" };
    let current: object = stateA;
    let releaseApply: (v: unknown) => void = () => {};
    bridge.rpc = (method) => {
      if (method === "recorder.state") return Promise.resolve(current);
      if (method === "recorder.steps") return Promise.resolve({ steps: [check], rev: 1 });
      if (method === "recorder.step.update") return new Promise((r) => (releaseApply = r));
      return Promise.reject(new Error(method));
    };
    try {
      resetRecorder();
      await refreshState();
      expect(useRecorder.getState().state?.session).toBe("A");
      // A: 글자 읽기·적용을 보내고 응답을 보류
      const ocr = draftTicket("s3");
      setExpectedDraft("s3", "A 초안");
      const applying = applyExpected("s3", "A 초안");
      // 녹화를 바꿔 B (같은 스텝 ID s3)에 새 초안
      current = stateB;
      await refreshState();
      expect(useRecorder.getState().state?.session).toBe("B");
      setExpectedDraft("s3", "B 초안");
      // 늦은 A 응답들
      expect(fillExpectedDraft(ocr, "A에서 읽은 글")).toBe(false);
      releaseApply({ step: { ...check, equals: "A 초안" }, rev: 2 });
      await applying;
      expect(useRecorder.getState().expectedDrafts).toEqual({ s3: "B 초안" });

      // 같은 녹화의 글자 읽기는 쓴다
      expect(fillExpectedDraft(draftTicket("s3"), "B에서 읽은 글")).toBe(true);
      expect(useRecorder.getState().expectedDrafts.s3).toBe("B에서 읽은 글");

      // 요청 중에 고친 초안은 적용 성공 뒤에도 남는다, 보낸 글 그대로면 지운다
      const second = applyExpected("s3", "B에서 읽은 글");
      setExpectedDraft("s3", "보내는 중 고침");
      releaseApply({ step: { ...check, equals: "B에서 읽은 글" }, rev: 3 });
      expect(await second).toBe(true);
      expect(useRecorder.getState().expectedDrafts.s3).toBe("보내는 중 고침");
      const third = applyExpected("s3", "보내는 중 고침");
      releaseApply({ step: { ...check, equals: "보내는 중 고침" }, rev: 4 });
      expect(await third).toBe(true);
      expect(useRecorder.getState().expectedDrafts).toEqual({});

      // reset 뒤의 늦은 읽기도 쓰지 않는다
      const late = draftTicket("s3");
      resetRecorder();
      await refreshState();
      expect(fillExpectedDraft(late, "늦은 글")).toBe(false);
      expect(useRecorder.getState().expectedDrafts).toEqual({});
    } finally {
      bridge.rpc = before;
    }
  });
});

function targetDoc(path: string, over: Partial<TargetDoc>): TargetDoc {
  return {
    path,
    instance: 1,
    status: "ready",
    error: null,
    isNew: true,
    baseRevision: null,
    savedSpec: null,
    spec: newSpec(),
    image: null,
    diagnostics: [],
    frame: null,
    frameSource: null,
    frameExpired: false,
    frameGen: 0,
    frameRequest: 0,
    frameLoading: false,
    template: null,
    preview: null,
    previewNote: null,
    previewSeq: 0,
    previewPending: false,
    edits: 0,
    reloadSeq: 0,
    saving: false,
    conflict: null,
    saveError: null,
    saved: null,
    saves: 0,
    origin: null,
    ...over,
  } as TargetDoc;
}

describe("target 영역 속성 → 속성 탭", () => {
  test("영역이 없으면 안내, 그리면 매칭 미리보기·클릭 지점·보조 패널. 탭 본문은 캔버스만", () => {
    const path = "targets/a.target.json";
    useTargets.setState({ docs: new Map([[path, targetDoc(path, {})]]) });
    setTabs([tab({ path, kind: "target" })], path);
    expect(panel()).toContain('data-part="target-props-empty"');
    const drawn = targetDoc(path, { template: [10, 10, 40, 30] });
    useTargets.setState({ docs: new Map([[path, drawn]]) });
    collapse();
    showProps(); // 판에서 영역을 놓으면 FrameView가 부른다
    const html = panel();
    expect(html).toContain('data-part="target-props"');
    expect(html).toContain('data-part="preview-panel"');
    expect(html).toContain('data-part="click-panel"');
    expect(html).toContain('data-part="ext-panels"');
    const body = render(<TargetEditorBody doc={drawn} adapter={fileTargetAdapter(path)} />);
    expect(body).not.toContain('data-part="preview-panel"');
    expect(body).not.toContain('data-part="click-panel"');
  });

  test("REC 탭에서 고친 스텝의 영역 속성도 속성 탭 (속성 창이 숨지 않는다)", () => {
    setTabs([tab({ path: REC_TAB_PATH, kind: "rec" })], REC_TAB_PATH);
    expect(panel()).toContain('data-part="inspector"');
    setTabs([tab({ path: "targets/a.target.json", kind: "target" })], "targets/a.target.json");
    expect(panel()).toContain('data-part="inspector"');
  });
});

function graphDoc(path: string, selected: string | null): GraphDoc {
  return {
    path,
    instance: 1,
    status: "ready",
    docId: "d1",
    refs: 1,
    refsConnection: null,
    baseRevision: "r1",
    value: { nodes: { n_a: { type: "x.unknown", version: 1 } } } as never,
    dirty: false,
    canonical: true,
    diagnostics: [],
    shapes: {},
    validateSeq: 0,
    error: null,
    conflict: null,
    view: { expanded: [], selected, selection: selected === null ? [] : [selected], viewport: null, focus: null, auto: new Map() },
    savedValue: null,
    history: EMPTY_HISTORY,
    saving: false,
    saveError: null,
    saves: 0,
    edits: 0,
    reloadSeq: 0,
    readOnly: false,
  };
}

describe("그래프 노드 → 마지막 실행 결과", () => {
  test("노드를 고르면 속성 아래 '마지막 실행 결과' 묶음, 하단 패널에는 결과 탭이 없다", async () => {
    const path = "tests/a.graph.json";
    useDocuments.setState({ docs: new Map([[path, graphDoc(path, null)]]) });
    setTabs([tab({ path, kind: "graph" })], path);
    expect(panel()).not.toContain('data-part="node-last-result"');
    useDocuments.setState({ docs: new Map([[path, graphDoc(path, "n_a")]]) });
    const html = panel();
    expect(html).toContain('data-part="node-last-result"');
    expect(html).toContain("마지막 실행 결과");
    expect(html).toMatch(/data-part="node-result" data-node="n_a"/);
    const { Panel } = await import("./Panel");
    useUi.setState({ panelOpenOther: true });
    const bottom = render(<Panel />);
    expect(bottom).toContain("실행 로그");
    expect(bottom).not.toContain("노드 결과");
  });
});

describe("탭을 바꾸면 그 탭에서 고른 것", () => {
  test("RUN 두 개·보고함: 활성 탭의 선택만 그린다", () => {
    const other = "ef56ab78";
    const a = step("a1", { status: "fail", evidence: true });
    useRunIndex.setState({
      runs: new Map([
        [RUN, runView({ index: index([a]), selected: "a1" })],
        [other, runView({ runId: other, index: index([a], { run_id: other }), selected: null })],
      ]),
    });
    const tabs = [tab({ path: runTabPath(RUN), kind: "run", runId: RUN }), tab({ path: runTabPath(other), kind: "run", runId: other }), tab({ path: REPORTS_TAB_PATH, kind: "reports" })];
    useReports.setState({ rows: [], selected: null, detail: null });
    setTabs(tabs, runTabPath(RUN));
    expect(panel()).toMatch(/data-part="evidence" data-step="a1"/);
    setTabs(tabs, runTabPath(other));
    expect(panel()).toContain('data-part="run-props-empty"');
    setTabs(tabs, REPORTS_TAB_PATH);
    expect(panel()).toContain('data-part="report-props-empty"');
    expect(panel()).not.toContain('data-part="evidence"');
    // 다시 돌아가면 기억한 스텝
    setTabs(tabs, runTabPath(RUN));
    expect(panel()).toMatch(/data-part="evidence" data-step="a1"/);
  });

  test("에이전트 탭을 보고 있어도 고르면 속성 탭, 승인 배지 자리는 그대로", () => {
    useUi.setState({ inspectorOpen: true, rightTab: "agent" });
    showProps();
    expect(useUi.getState().rightTab).toBe("props");
    expect(panel()).toContain('data-part="agent-tab"');
  });
});

describe("폭: 최대 창 폭 50%, 탭 종류별 기억", () => {
  test("탭 종류마다 따로 기억하고, 그래프·그 밖은 기존 칸", () => {
    expect(inspectorWidthOf(useUi.getState(), "run")).toBeNull(); // 처음은 기본 폭
    setInspectorWidth("run", 700);
    setInspectorWidth("reports", 640);
    setInspectorWidth("graph", 400);
    const s = useUi.getState();
    expect(inspectorWidthOf(s, "run")).toBe(700);
    expect(inspectorWidthOf(s, "reports")).toBe(640);
    expect(inspectorWidthOf(s, "graph")).toBe(400);
    expect(inspectorWidthOf(s, "file")).toBe(400);
    expect(inspectorWidthOf(s, "target")).toBeNull();
    expect(s.inspectorWidth).toBe(400);
    // 저장·읽기
    const saved = JSON.parse(JSON.stringify(layoutOf(s)));
    // 주 프로세스 layoutSet은 평평한 객체(값은 수·참거짓·null, 16칸 이하)만 받는다
    expect(Object.keys(saved).length).toBeLessThanOrEqual(16);
    expect(Object.values(saved).every((v) => v === null || typeof v === "number" || typeof v === "boolean")).toBe(true);
    expect(saved).toMatchObject({ inspectorWidth: 400, inspectorWidth_run: 700, inspectorWidth_reports: 640, inspectorWidth_target: null });
    expect(parseLayout(saved)).toMatchObject({ inspectorWidth: 400, inspectorWidths: { run: 700, reports: 640 } });
    expect(parseLayout({ inspectorWidth_run: "x", inspectorWidth_rec: 500, inspectorWidth_other: 300 }).inspectorWidths).toEqual({ rec: 500 });
    // 두 번 눌러 기본 폭
    setInspectorWidth("run", null);
    expect(inspectorWidthOf(useUi.getState(), "run")).toBeNull();
  });

  test("RUN 탭이면 그 폭으로 그린다, 손잡이 최대는 창 폭 50%", () => {
    setInspectorWidth("run", 700);
    useRunIndex.setState({ runs: new Map([[RUN, runView({ index: index([]) })]]) });
    setTabs([tab({ path: runTabPath(RUN), kind: "run", runId: RUN })], runTabPath(RUN));
    expect(panel()).toContain("flex-basis:701px");
    // 그리는 폭은 늘 창 폭의 50% 이하 (기억한 폭이 더 커도 — 검수 M4)
    expect(panel()).toContain("max-width:calc(50vw + 1px)");
    expect(RIGHT_MAX_FRACTION).toBe(0.5);
    expect(clampWidth(1200, 260, 10_000, 1600, RIGHT_MAX_FRACTION)).toBe(800);
    expect(clampWidth(700, 260, 10_000, 1600, RIGHT_MAX_FRACTION)).toBe(700);
    expect(clampWidth(100, 260, 10_000, 1600, RIGHT_MAX_FRACTION)).toBe(260);
  });
});
