// 사이드바 "실행 기록" 목록 (M3 계획 2.10): run.list 요약을 날짜 묶음(오늘·어제·M월 D일)으로 보이고, 진행 중
// 실행은 맨 위 "실행 중". 아래로 끝까지 내리면 다음 쪽(before 커서). 실행 ID는 `#<앞 4자>`(겹치면 더 늘림, C24).
// 배지: 디버거 개입(debug_intervened)·불안정(flaky)·검증 없음(code no_assertion)
import type { ResultOf } from "@kookabug/schema";
import { create } from "zustand";
import { displayName } from "../explorer/tree";
import { client, toRpcError, type RpcCall } from "../rpc/client";

export type RunSummary = ResultOf<"run.list">["runs"][number];

export const LIST_PAGE = 50;

export type Tone = "pass" | "fail" | "error" | "skipped" | "running" | "cancelled";

export function toneOf(run: RunSummary): Tone {
  if (run.state === "running") return "running";
  const verdict = run.outcome?.verdict;
  if (verdict === "pass") return "pass";
  if (verdict === "fail") return "fail";
  if (verdict === "skipped") return "skipped";
  if (run.code === "cancelled") return "cancelled";
  return "error";
}

export const VERDICT_LABEL: Record<Tone, string> = {
  pass: "성공",
  fail: "실패",
  error: "오류",
  skipped: "건너뜀",
  running: "실행 중",
  cancelled: "취소",
};

export interface Badge {
  kind: "debug" | "flaky" | "no_assertion" | "agent_control";
  text: string;
}

export function badgesOf(run: RunSummary): Badge[] {
  const out: Badge[] = [];
  if (run.debug_intervened === true) out.push({ kind: "debug", text: "디버거 개입" });
  if (run.flaky === true) out.push({ kind: "flaky", text: "불안정" });
  if (run.code === "no_assertion") out.push({ kind: "no_assertion", text: "검증 없음" });
  // 에이전트의 게임 조작(한 스텝 제어 실행, M5 3.9·U4) — 감사 기록으로 남긴다
  if (run.source === "agent_control") out.push({ kind: "agent_control", text: "에이전트 제어" });
  return out;
}

/** 에이전트 제어 실행의 기록 강제 (M7 R2, run.json record_override): 기록 뷰어 머리 줄로 사람에게 알린다 */
export function recordOverrideText(run: unknown): string | null {
  const override = (run as { record_override?: { by?: unknown } } | null | undefined)?.record_override;
  if (override?.by !== "agent_control") return null;
  return "에이전트 제어 실행 · 이미지 기록 없음 · 비밀값 가림";
}

/** 경과 글 (3분 08초, 12.4초) */
export function formatDuration(ms: number): string {
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}초`;
  const total = Math.round(ms / 1000);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h}시간 ${m}분`;
  return `${m}분 ${String(s).padStart(2, "0")}초`;
}

/** 바이트 글 (12.4 GB) */
export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(1)} GB`;
}

/** 상태 바 보관 문구 (시안 "보관: 통과 14일 · 실패 60일 · 12.4 GB"). 정리는 보류 H1 — 정책 문구만 */
export function retentionText(retention: { passed_days: number; failed_days: number } | undefined, runsBytes: number | null): string | null {
  if (retention === undefined) return null;
  const size = runsBytes === null ? "" : ` · ${formatBytes(runsBytes)}`;
  return `보관: 통과 ${retention.passed_days}일 · 실패 ${retention.failed_days}일${size}`;
}

const VIDEO_MODE: Record<string, string> = { on: "켬", failed_only: "실패만", off: "끔" };

/**
 * 상태 바 영상 정책 문구 (M4 T12, STATE ⑦): "영상: 실패만 (워크스페이스 기본값)", "영상: 끔 (kookabug.json)".
 * 출처는 그 값을 정한 층의 파일(# 앞)이다. 정책을 모르면(옛 실행) null
 */
export function videoPolicyText(policy: { mode: string; source: string | null } | undefined): string | null {
  if (policy === undefined) return null;
  const mode = VIDEO_MODE[policy.mode] ?? policy.mode;
  const source = policy.source === null ? "워크스페이스 기본값" : policy.source.split("#", 1)[0];
  return `영상: ${mode} (${source})`;
}

/** 메타 줄: 결과 · 실패 위치(또는 사유) · 경과 · build */
export function metaOf(run: RunSummary): string {
  const parts: string[] = [VERDICT_LABEL[toneOf(run)]];
  if (run.failure_title !== undefined && run.failure_title !== "") parts.push(run.failure_title);
  else if (run.state === "ended" && run.reason !== undefined && run.reason !== "" && run.outcome?.verdict !== "pass") parts.push(run.reason);
  if (run.duration_ms !== undefined) parts.push(formatDuration(run.duration_ms));
  if (typeof run.game_build === "string" && run.game_build !== "") parts.push(`build=${run.game_build}`);
  return parts.join(" · ");
}

/** 실행 ID 짧은 표시: 목록에서 겹치지 않는 가장 짧은 앞부분 (4자 이상) */
export function shortIds(ids: readonly string[]): Map<string, string> {
  const out = new Map<string, string>();
  const unique = [...new Set(ids)];
  for (const id of unique) {
    let n = Math.min(4, id.length);
    while (n < id.length && unique.some((o) => o !== id && o.startsWith(id.slice(0, n)))) n++;
    out.set(id, id.slice(0, n));
  }
  return out;
}

export function testName(run: Pick<RunSummary, "graph">): string {
  return displayName(run.graph);
}

function dayKey(d: Date): string {
  return `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`;
}

/** 날짜 묶음 이름 (오늘·어제·M월 D일) */
export function dayLabel(at: Date, now: Date): string {
  if (dayKey(at) === dayKey(now)) return "오늘";
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (dayKey(at) === dayKey(yesterday)) return "어제";
  return `${at.getMonth() + 1}월 ${at.getDate()}일`;
}

export interface RunGroup {
  name: string;
  runs: RunSummary[];
}

/** 진행 중 실행은 맨 위 "실행 중", 나머지는 시작 날짜 묶음 (받은 순서 = 최신순 그대로) */
export function groupRuns(runs: readonly RunSummary[], now: Date): RunGroup[] {
  const groups: RunGroup[] = [];
  const running = runs.filter((r) => r.state === "running");
  if (running.length > 0) groups.push({ name: "실행 중", runs: running });
  for (const run of runs) {
    if (run.state === "running") continue;
    const name = run.started_at === null ? "시각 모름" : dayLabel(new Date(run.started_at), now);
    const last = groups[groups.length - 1];
    if (last !== undefined && last.name === name && last.name !== "실행 중") last.runs.push(run);
    else groups.push({ name, runs: [run] });
  }
  return groups;
}

/** 지난 열람 이후 실패·오류로 끝난 실행 수 (액티비티 바 배지) */
export function failuresSince(runs: readonly RunSummary[], seenAt: number): number {
  return runs.filter((r) => {
    const tone = toneOf(r);
    if (tone !== "fail" && tone !== "error") return false;
    const at = r.started_at === null ? 0 : Date.parse(r.started_at);
    return at > seenAt;
  }).length;
}

// ── 목록 상태 ─────────────────────────────────────────────────────

export interface RunListState {
  runs: RunSummary[];
  next: string | null;
  loading: boolean;
  error: string | null;
  runsBytes: number | null;
  /** 지난 열람 시각 (실행 기록을 마지막으로 연 때, ms) */
  seenAt: number;
}

const INITIAL: RunListState = { runs: [], next: null, loading: false, error: null, runsBytes: null, seenAt: Date.now() };

/** 받은 쪽을 합친다: 같은 실행은 새 것, 시작 시각 최신순 */
export function mergeRuns(base: readonly RunSummary[], incoming: readonly RunSummary[]): RunSummary[] {
  const byId = new Map(base.map((r) => [r.run_id, r]));
  for (const r of incoming) byId.set(r.run_id, r);
  return [...byId.values()].sort((a, b) => {
    if (a.state !== b.state) return a.state === "running" ? -1 : 1;
    const at = (r: RunSummary) => (r.started_at === null ? 0 : Date.parse(r.started_at));
    return at(b) - at(a) || (a.run_dir < b.run_dir ? 1 : -1);
  });
}

export class RunListModel {
  readonly store = create<RunListState>(() => ({ ...INITIAL }));
  private generation = 0;
  private reloadAgain = false;
  private reloading = false;

  constructor(private readonly call: RpcCall) {}

  /** 첫 쪽을 다시 읽어 합친다 (실행 시작·끝, 처음 열 때) */
  async reload(): Promise<void> {
    if (this.reloading) {
      this.reloadAgain = true;
      return;
    }
    this.reloading = true;
    const gen = this.generation;
    try {
      this.store.setState({ loading: true });
      const r = await this.call("run.list", { limit: LIST_PAGE });
      if (gen !== this.generation) return;
      this.store.setState((s) => {
        // 진행 중이던 실행이 끝났으면 새 요약으로 바뀐다. 첫 쪽보다 오래된 쪽은 그대로 둔다
        const kept = s.runs.filter((x) => !r.runs.some((y) => y.run_id === x.run_id));
        const firstLoad = s.runs.length === 0;
        return {
          runs: mergeRuns(kept, r.runs),
          next: firstLoad ? (r.next ?? null) : s.next,
          loading: false,
          error: null,
          runsBytes: r.runs_bytes ?? s.runsBytes,
        };
      });
    } catch (err) {
      if (gen === this.generation) this.store.setState({ loading: false, error: toRpcError(err).message });
    } finally {
      this.reloading = false;
      if (this.reloadAgain && gen === this.generation) {
        this.reloadAgain = false;
        void this.reload();
      }
    }
  }

  /** 다음 쪽 (끝까지 내렸을 때) */
  async more(): Promise<void> {
    const s = this.store.getState();
    if (s.loading || s.next === null) return;
    const gen = this.generation;
    this.store.setState({ loading: true });
    try {
      const r = await this.call("run.list", { limit: LIST_PAGE, before: s.next });
      if (gen !== this.generation) return;
      this.store.setState((x) => ({ runs: mergeRuns(x.runs, r.runs), next: r.next ?? null, loading: false, error: null }));
    } catch (err) {
      if (gen === this.generation) this.store.setState({ loading: false, error: toRpcError(err).message });
    }
  }

  /** 실행 기록을 봤다 (배지를 비운다) */
  markSeen(at = Date.now()): void {
    this.store.setState({ seenAt: at });
  }

  /** 프로젝트를 바꿨다 */
  reset(): void {
    this.generation++;
    this.reloading = false;
    this.reloadAgain = false;
    this.store.setState({ ...INITIAL, seenAt: Date.now() });
  }
}

export const runListModel = new RunListModel((method, params) => client().call(method, params));
export const useRunList = runListModel.store;
