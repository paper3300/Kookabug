// 실행 이벤트 → 화면 상태 (M2 계획 2.8 "강조 규칙", T11). 순수 함수만 둔다 (highlight.test.ts)
// - 기록(RunTrace)은 seq 순서로만 받는다: 앞서 받은 seq 이하(역행·중복)는 버린다. 빈틈은 구독 커서
//   (rpc/runCursor.ts)가 막는다
// - 열린 스텝 = step.start가 있고 step.end가 없는 스텝. 가장 안쪽(가장 늦게 시작한) 열린 스텝의 호출
//   경로를 실행한 그래프(루트)부터 따라간다. 루트 탭에서는 경로 첫 노드(서브그래프 안쪽이면 호출 노드)를,
//   그 경로가 지나는 서브그래프 파일이 탭에 열려 있으면 그 탭에서 그 깊이의 노드를 강조한다
// - 서브그래프 파일은 실행 스냅샷의 호출 관계(daemon run.status calls)로 찾는다. 편집 버퍼의 config.graph나
//   조상 탭이 열려 있는지와 무관하다. 탭의 지금 버퍼는 그 노드 ID가 아직 있는지만 본다: 버퍼에 없는 노드
//   ID의 이벤트는 강조하지 않고 실행 로그에만 쓴다
// - 기억하는 양은 묶어 둔다: 호출 경로마다 마지막 스텝·마지막으로 끝난 스텝, 열린 스텝, 로그 줄 LOG_MAX개
import { graphNodes, isObject, own, type GraphValue } from "../graph/model";

export const LOG_MAX = 2000;

/** events.jsonl 한 줄 (events.schema.json). 필요한 칸만 읽는다 */
export interface RunEvent {
  event: string;
  seq: number;
  t: string;
  [key: string]: unknown;
}

export type StepStatus = "success" | "fail" | "error" | "cancelled";

export interface StepEnd {
  status: StepStatus;
  exit: string | null;
  durationMs: number;
  t: number;
  outputs: Record<string, unknown>;
  error: { code: string; message: string } | null;
  message: string | null;
  artifacts: string[];
  omitted: unknown[];
  /** 서브그래프 호출이면 이번 실행에 쓴 스냅샷 파일 */
  graph: string | null;
  /** step.end 없이 실행이 끝남 (중단된 스텝) */
  interrupted: boolean;
}

export interface StepRecord {
  step: string;
  node: string;
  path: readonly string[];
  iteration: number | null;
  attempt: number;
  startSeq: number;
  startT: number;
  end: StepEnd | null;
}

export type LogLevel = "RUN" | "OK" | "WARN" | "INFO" | "FAIL" | "ERROR" | "STOP";

export interface LogEntry {
  seq: number;
  t: number;
  level: LogLevel;
  /** 노드 스텝의 호출 경로. 실행 전체 줄이면 null */
  path: readonly string[] | null;
  message: string;
}

export interface RunEndInfo {
  verdict: string;
  code: string;
  reason: string;
  t: number;
  durationMs: number | null;
}

export interface RunTrace {
  runId: string;
  /** 실행한 테스트 그래프 (run.start) */
  graph: string | null;
  lastSeq: number;
  startT: number | null;
  /** 열린 스텝 (시작 순서) */
  open: ReadonlyMap<string, StepRecord>;
  /** 호출 경로 → 그 경로의 마지막 스텝 (열려 있을 수 있다: 상태 줄) */
  latest: ReadonlyMap<string, StepRecord>;
  /** 호출 경로 → 그 경로의 마지막으로 끝난 스텝 (다음 회차가 열려도 남는다: 노드 결과 패널) */
  completed: ReadonlyMap<string, StepRecord>;
  /** 반복 노드 호출 경로 → 지금 회차 (body로 나간 마지막 index + 1) */
  loops: ReadonlyMap<string, number>;
  log: readonly LogEntry[];
  /** 끝난 스텝 수 (step.end) */
  stepsEnded: number;
  end: RunEndInfo | null;
}

export function emptyTrace(runId: string, graph: string | null = null): RunTrace {
  return {
    runId,
    graph,
    lastSeq: 0,
    startT: null,
    open: new Map(),
    latest: new Map(),
    completed: new Map(),
    loops: new Map(),
    log: [],
    stepsEnded: 0,
    end: null,
  };
}

export const pathKey = (path: readonly string[]): string => JSON.stringify(path);

function str(v: unknown): string | null {
  return typeof v === "string" ? v : null;
}

function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function time(t: unknown): number {
  const ms = typeof t === "string" ? Date.parse(t) : Number.NaN;
  return Number.isFinite(ms) ? ms : 0;
}

function pushLog(log: readonly LogEntry[], entry: LogEntry): LogEntry[] {
  const next = log.length >= LOG_MAX ? log.slice(log.length - LOG_MAX + 1) : log.slice();
  next.push(entry);
  return next;
}

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.max(0, Math.round(ms))}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const s = Math.floor(ms / 1000);
  return `${Math.floor(s / 60)}m ${s % 60}s`;
}

/** 실행 로그 시각: 실행 시작부터 `HH:MM:SS.mmm` (시안 "01:12:04.331") */
export function formatClock(ms: number): string {
  const v = Math.max(0, Math.floor(ms));
  const p = (n: number, w = 2) => String(n).padStart(w, "0");
  return `${p(Math.floor(v / 3_600_000))}:${p(Math.floor(v / 60_000) % 60)}:${p(Math.floor(v / 1000) % 60)}.${p(v % 1000, 3)}`;
}

/** 상태 바 경과 시간 `H:MM:SS` (시안 "1:12:04") */
export function formatElapsed(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const p = (n: number) => String(n).padStart(2, "0");
  return `${Math.floor(s / 3600)}:${p(Math.floor(s / 60) % 60)}:${p(s % 60)}`;
}

/** 회차·한도 (시안 "3,412 / 10,000") */
export function formatCount(n: number): string {
  return n.toLocaleString("en-US");
}

function stepEndOf(e: RunEvent): StepEnd {
  const status = e.status === "fail" || e.status === "error" || e.status === "cancelled" ? e.status : "success";
  const error = isObject(e.error) ? { code: String(e.error.code ?? ""), message: String(e.error.message ?? "") } : null;
  return {
    status,
    exit: str(e.exit),
    durationMs: num(e.duration_ms) ?? 0,
    t: time(e.t),
    outputs: isObject(e.outputs) ? e.outputs : {},
    error,
    message: str(e.message),
    artifacts: Array.isArray(e.artifacts) ? e.artifacts.filter((a): a is string => typeof a === "string") : [],
    omitted: Array.isArray(e.omitted) ? e.omitted : [],
    graph: str(e.graph),
    interrupted: false,
  };
}

const END_LEVEL: Record<StepStatus, LogLevel> = { success: "OK", fail: "FAIL", error: "ERROR", cancelled: "STOP" };

function endMessage(end: StepEnd): string {
  const parts: string[] = [];
  if (end.exit !== null) parts.push(end.exit);
  if (end.error !== null) parts.push(`${end.error.code}: ${end.error.message}`);
  else if (end.message !== null) parts.push(end.message);
  if (end.artifacts.length > 0) parts.push(`증거 ${end.artifacts.join(", ")}`);
  parts.push(formatDuration(end.durationMs));
  return parts.join(" · ");
}

const LOG_EVENT_LEVEL: Record<string, LogLevel | undefined> = { info: "INFO", warn: "WARN", error: "ERROR" };

const VERDICT_LEVEL: Record<string, LogLevel> = { pass: "OK", fail: "FAIL", error: "ERROR", skipped: "INFO" };

/**
 * 이벤트 하나를 기록에 더한다. 앞서 받은 seq 이하면 그대로 돌려준다(역행·중복 무시). 값은 바꾸지 않고
 * 바뀐 부분만 새로 만든다
 */
export function applyEvent(trace: RunTrace, e: RunEvent): RunTrace {
  if (typeof e.seq !== "number" || !Number.isInteger(e.seq) || e.seq <= trace.lastSeq) return trace;
  const next: RunTrace = { ...trace, lastSeq: e.seq };
  const t = time(e.t);
  switch (e.event) {
    case "run.start": {
      next.graph = str(e.graph) ?? trace.graph;
      next.startT = t;
      next.log = pushLog(trace.log, {
        seq: e.seq,
        t,
        level: "INFO",
        path: null,
        message: `실행 ${trace.runId} 시작 · ${next.graph ?? ""}`,
      });
      break;
    }
    case "step.start": {
      const step = str(e.step);
      const node = str(e.node);
      if (step === null || node === null) break;
      const path = Array.isArray(e.path) && e.path.every((p) => typeof p === "string") ? (e.path as string[]) : [node];
      const rec: StepRecord = {
        step,
        node,
        path,
        iteration: num(e.iteration),
        attempt: num(e.attempt) ?? 1,
        startSeq: e.seq,
        startT: t,
        end: null,
      };
      const open = new Map(trace.open);
      open.set(step, rec);
      const latest = new Map(trace.latest);
      latest.set(pathKey(path), rec);
      next.open = open;
      next.latest = latest;
      break;
    }
    case "step.end": {
      const step = str(e.step);
      const rec = step === null ? undefined : trace.open.get(step);
      const end = stepEndOf(e);
      next.stepsEnded = trace.stepsEnded + 1;
      if (rec === undefined) {
        next.log = pushLog(trace.log, { seq: e.seq, t, level: END_LEVEL[end.status], path: null, message: endMessage(end) });
        break;
      }
      // attempt는 끝 이벤트의 값이 마지막 시도 번호다 (재시도해도 step.start는 한 번)
      const done: StepRecord = { ...rec, attempt: num(e.attempt) ?? rec.attempt, end };
      const open = new Map(trace.open);
      open.delete(rec.step);
      next.open = open;
      const key = pathKey(rec.path);
      const current = trace.latest.get(key);
      if (current === undefined || current.startSeq <= rec.startSeq) {
        const latest = new Map(trace.latest);
        latest.set(key, done);
        next.latest = latest;
      }
      const last = trace.completed.get(key);
      if (last === undefined || last.startSeq <= rec.startSeq) {
        const completed = new Map(trace.completed);
        completed.set(key, done);
        next.completed = completed;
      }
      const index = num(end.outputs.index);
      if (end.exit === "body" && index !== null) {
        const loops = new Map(trace.loops);
        loops.set(key, index + 1);
        next.loops = loops;
      }
      next.log = pushLog(trace.log, { seq: e.seq, t, level: END_LEVEL[end.status], path: rec.path, message: endMessage(end) });
      break;
    }
    case "attempt.end": {
      const rec = trace.open.get(str(e.step) ?? "");
      const exit = str(e.exit);
      const message = str(e.message);
      next.log = pushLog(trace.log, {
        seq: e.seq,
        t,
        level: "WARN",
        path: rec?.path ?? null,
        message: [`시도 ${num(e.attempt) ?? "?"} 실패`, exit, message, formatDuration(num(e.duration_ms) ?? 0)]
          .filter((p) => p !== null && p !== "")
          .join(" · "),
      });
      break;
    }
    case "log": {
      const level = LOG_EVENT_LEVEL[str(e.level) ?? ""];
      if (level === undefined) break; // debug는 쓰지 않는다
      const rec = trace.open.get(str(e.step) ?? "");
      const node = str(e.node);
      next.log = pushLog(trace.log, {
        seq: e.seq,
        t,
        level,
        path: rec?.path ?? (node === null ? null : [node]),
        message: str(e.message) ?? "",
      });
      break;
    }
    case "cancel.requested":
      next.log = pushLog(trace.log, { seq: e.seq, t, level: "WARN", path: null, message: `취소 요청 (${str(e.reason) ?? ""})` });
      break;
    case "control.lost":
      next.log = pushLog(trace.log, { seq: e.seq, t, level: "WARN", path: null, message: "제어 채널이 끊겼어요" });
      break;
    case "input.recovered":
      next.log = pushLog(trace.log, {
        seq: e.seq,
        t,
        level: "INFO",
        path: null,
        message: `눌린 입력을 뗐어요 (실행 ${str(e.from_run) ?? ""})`,
      });
      break;
    case "run.end": {
      const verdict = str(e.verdict) ?? "error";
      next.end = {
        verdict,
        code: str(e.code) ?? "",
        reason: str(e.reason) ?? "",
        t,
        durationMs: num(e.duration_ms),
      };
      // step.end 없이 끝난 스텝은 중단된 것이다 (events 스키마 StepEndEvent 설명)
      if (trace.open.size > 0) {
        const latest = new Map(trace.latest);
        for (const rec of trace.open.values()) {
          const key = pathKey(rec.path);
          if (latest.get(key)?.step !== rec.step) continue;
          latest.set(key, {
            ...rec,
            end: {
              status: "cancelled",
              exit: null,
              durationMs: Math.max(0, t - rec.startT),
              t,
              outputs: {},
              error: null,
              message: null,
              artifacts: [],
              omitted: [],
              graph: null,
              interrupted: true,
            },
          });
        }
        next.open = new Map();
        next.latest = latest;
      }
      const dur = next.end.durationMs;
      next.log = pushLog(trace.log, {
        seq: e.seq,
        t,
        level: VERDICT_LEVEL[verdict] ?? "INFO",
        path: null,
        message: [`판정 ${verdict}`, next.end.code, next.end.reason, dur === null ? null : formatDuration(dur)]
          .filter((p) => p !== null && p !== "")
          .join(" · "),
      });
      break;
    }
    default:
      break;
  }
  return next;
}

// ── 그래프 따라가기 ──────────────────────────────────────────────

/** 열린 탭의 버퍼 값 (경로 → 값). 열려 있지 않으면 null. 노드가 아직 있는지·제목을 볼 때만 쓴다 */
export type GraphLookup = (path: string) => GraphValue | null;

/**
 * 실행 스냅샷의 호출 관계 (run.status calls): 그래프 파일 → 호출 노드 → 부르는 서브그래프. 실행에 고정이다:
 * 실행 중에 호출 노드의 config.graph를 고치거나 조상 탭을 닫아도 바뀌지 않는다
 */
export type CallMap = Readonly<Record<string, Readonly<Record<string, string>>>>;

function nodeRaw(value: GraphValue | null, id: string): Record<string, unknown> | null {
  if (value === null) return null;
  const nodes = own(value, "nodes");
  const raw = own(nodes, id);
  return isObject(raw) ? raw : null;
}

function calleeOf(calls: CallMap, graph: string, id: string): string | null {
  const inGraph = Object.hasOwn(calls, graph) ? calls[graph] : undefined;
  return inGraph !== undefined && Object.hasOwn(inGraph, id) ? inGraph[id] : null;
}

/** 호출 경로의 깊이마다 그 노드가 들어 있는 그래프 파일 (스냅샷 호출 관계로). 모르는 깊이부터 null */
export function framesOf(root: string | null, path: readonly string[], calls: CallMap): (string | null)[] {
  const frames: (string | null)[] = [];
  let graph = root;
  for (let i = 0; i < path.length; i++) {
    frames.push(graph);
    graph = graph === null ? null : calleeOf(calls, graph, path[i]);
  }
  return frames;
}

/** 호출 관계를 몰라 따라갈 수 없는 첫 호출 (그래프·노드). 다 알면 null */
export function unresolvedCall(root: string | null, path: readonly string[], calls: CallMap): string | null {
  const frames = framesOf(root, path, calls);
  for (let i = 1; i < frames.length; i++) {
    if (frames[i] === null) return frames[i - 1] === null ? null : JSON.stringify([frames[i - 1], path[i - 1]]);
  }
  return null;
}

/** 스텝을 쓸 노드 이름: 그 깊이의 그래프 파일이 열려 있으면 버퍼의 제목, 아니면 노드 ID */
export function stepLabel(
  root: string | null,
  path: readonly string[],
  calls: CallMap,
  lookup: GraphLookup,
  typeTitle: (type: string) => string | null = () => null,
): string {
  if (path.length === 0) return "";
  const frames = framesOf(root, path, calls);
  const depth = path.length - 1;
  const graph = frames[depth];
  const raw = nodeRaw(graph === null ? null : lookup(graph), path[depth]);
  const title = str(own(raw, "title"));
  if (title !== null && title !== "") return title;
  const type = str(own(raw, "type"));
  return (type === null ? null : typeTitle(type)) ?? path[depth];
}

// ── 탭 하나의 노드 상태 ─────────────────────────────────────────

export type RunTone = "run" | "ok" | "fail" | "error" | "muted";

export interface NodeRunView {
  /** 이 노드의 마지막 스텝 (열려 있을 수 있다) */
  step: StepRecord;
  /** 이 노드의 마지막으로 끝난 스텝 (노드 결과 패널. 다음 회차가 열려 있어도 앞 결과가 남는다) */
  result: StepRecord | null;
  /** 강조 (가장 안쪽 열린 스텝이 지나는 노드) */
  highlight: boolean;
  tone: RunTone;
  /** 흐르는 시간 표시면 시작 시각(ms, 화면이 "● 1.4s"로 쓴다). 아니면 null이고 text를 쓴다 */
  since: number | null;
  text: string;
}

export interface TabRunView {
  nodes: ReadonlyMap<string, NodeRunView>;
  /** 이 탭이 지금 실행에 걸려 있고 실행이 아직 끝나지 않음 (스텝이 없는 노드는 아직 닿지 않은 노드) */
  running: boolean;
}

export interface TabInput {
  path: string;
  value: GraphValue;
}

const STATUS_TONE: Record<StepStatus, RunTone> = { success: "ok", fail: "fail", error: "error", cancelled: "muted" };
const STATUS_MARK: Record<StepStatus, string> = { success: "✓", fail: "✕", error: "✕", cancelled: "■" };

function loopText(rec: StepRecord, count: number, limit: number | null, running: boolean): Pick<NodeRunView, "tone" | "text"> {
  const label = `${formatCount(count)} / ${limit === null ? "?" : formatCount(limit)}`;
  const end = rec.end;
  if (end === null) return { tone: running ? "run" : "muted", text: label };
  if (end.exit === "body") return running ? { tone: "run", text: label } : { tone: "muted", text: `■ ${label}` };
  return { tone: STATUS_TONE[end.status], text: `${STATUS_MARK[end.status]} ${label}` };
}

/**
 * 탭 하나(그래프 파일 하나)의 노드별 실행 상태와 강조. 스텝이 어느 파일의 노드인지는 실행 스냅샷의 호출
 * 관계(calls)로 정하고, 탭의 지금 버퍼는 그 노드 ID가 아직 있는지만 본다. loopLimit은 노드 타입이 반복
 * 노드면 한도 입력 이름 (times·max_iterations)
 */
export function tabRunView(
  trace: RunTrace,
  tab: TabInput,
  calls: CallMap,
  loopLimit: (type: string) => string | null = () => null,
): TabRunView {
  const running = trace.end === null;
  const nodes = new Map(graphNodes(tab.value).map((n) => [n.id, n]));
  const frameCache = new Map<string, (string | null)[]>();
  const frames = (path: readonly string[]) => {
    const key = pathKey(path);
    let f = frameCache.get(key);
    if (f === undefined) frameCache.set(key, (f = framesOf(trace.graph, path, calls)));
    return f;
  };
  const inTab = (rec: StepRecord) => {
    const depth = rec.path.length - 1;
    return frames(rec.path)[depth] === tab.path && nodes.has(rec.path[depth]);
  };

  const chosen = new Map<string, { rec: StepRecord; key: string }>();
  for (const [key, rec] of trace.latest) {
    if (!inTab(rec)) continue;
    const id = rec.path[rec.path.length - 1];
    const prev = chosen.get(id);
    if (prev === undefined || prev.rec.startSeq < rec.startSeq) chosen.set(id, { rec, key });
  }
  const results = new Map<string, StepRecord>();
  for (const rec of trace.completed.values()) {
    if (!inTab(rec)) continue;
    const id = rec.path[rec.path.length - 1];
    const prev = results.get(id);
    if (prev === undefined || prev.startSeq < rec.startSeq) results.set(id, rec);
  }

  // 가장 안쪽 열린 스텝 = 가장 늦게 시작한 열린 스텝
  let innermost: StepRecord | null = null;
  if (running) for (const rec of trace.open.values()) if (innermost === null || rec.startSeq > innermost.startSeq) innermost = rec;
  let highlight: string | null = null;
  if (innermost !== null) {
    const f = frames(innermost.path);
    const depth = f.indexOf(tab.path);
    if (depth >= 0 && nodes.has(innermost.path[depth])) highlight = innermost.path[depth];
  }

  const out = new Map<string, NodeRunView>();
  for (const [id, { rec, key }] of chosen) {
    const node = nodes.get(id)!;
    const limitName = loopLimit(node.type);
    const count = trace.loops.get(key);
    const base = { step: rec, result: results.get(id) ?? null, highlight: false };
    let view: NodeRunView;
    if (limitName !== null && count !== undefined) {
      const limit = num(node.in[limitName]);
      view = { ...base, since: null, ...loopText(rec, count, limit, running) };
    } else if (rec.end === null) {
      view = running
        ? { ...base, tone: "run", since: rec.startT, text: "" }
        : { ...base, tone: "muted", since: null, text: "■ 중단" };
    } else {
      const end = rec.end;
      view = {
        ...base,
        tone: STATUS_TONE[end.status],
        since: null,
        text: end.interrupted ? "■ 중단" : `${STATUS_MARK[end.status]} ${formatDuration(end.durationMs)}`,
      };
    }
    out.set(id, view);
  }
  if (highlight !== null && innermost !== null) {
    // 강조 노드의 스텝 = 가장 안쪽 열린 스텝의 그 깊이 조상 (호출 노드면 그 호출 스텝). 조상 스텝은 안쪽
    // 스텝이 도는 동안 늘 열려 있다
    const depth = frames(innermost.path).indexOf(tab.path);
    const prefix = pathKey(innermost.path.slice(0, depth + 1));
    let step: StepRecord = innermost;
    for (const rec of trace.open.values()) if (pathKey(rec.path) === prefix) step = rec;
    out.set(highlight, { step, result: results.get(highlight) ?? null, highlight: true, tone: "run", since: step.startT, text: "" });
  }
  // 이 실행과 상관없는 탭(다른 테스트·아직 닿지 않은 서브그래프)은 "아직 닿지 않음"으로 흐리게 하지 않는다
  const related = tab.path === trace.graph || out.size > 0;
  return { nodes: out, running: running && related };
}

/** 실행 중 화면에 쓸 흐르는 시간 ("● 1.4s") */
export function runningText(since: number, now: number): string {
  const ms = Math.max(0, now - since);
  return `● ${ms < 60_000 ? `${(ms / 1000).toFixed(1)}s` : formatDuration(ms)}`;
}

/** 상태 바의 반복 표시: 가장 최근에 회차가 바뀐 반복 */
export function loopProgress(
  trace: RunTrace,
  calls: CallMap,
  lookup: GraphLookup,
  loopLimit: (type: string) => string | null,
): { count: number; limit: number | null } | null {
  let best: { rec: StepRecord; count: number } | null = null;
  for (const [key, count] of trace.loops) {
    const rec = trace.latest.get(key);
    if (rec === undefined || (best !== null && best.rec.startSeq > rec.startSeq)) continue;
    best = { rec, count };
  }
  if (best === null) return null;
  const path = best.rec.path;
  const depth = path.length - 1;
  const graph = framesOf(trace.graph, path, calls)[depth];
  const raw = nodeRaw(graph === null ? null : lookup(graph), path[depth]);
  const type = str(own(raw, "type"));
  const name = type === null ? null : loopLimit(type);
  const limit = name === null ? null : num(own(own(raw, "in"), name));
  return { count: best.count, limit };
}
