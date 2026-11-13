// 녹화 상태·스텝 (M4 계획 2.9·2.11, T9·T10). daemon 녹화 세션을 따라간다:
// - recorder.changed(소유 연결은 rev·counts·warnings, 다른 연결은 state만) → recorder.state, 소유면 recorder.steps
// - 시작 순서 (2.9): 주 프로세스가 녹화 단축키 등록에 성공한 뒤에만 recorder.start. 실패하면 보내지 않는다
//   (주 프로세스 문지기도 한 번 더 막는다, main/shortcuts.ts)
// - 원문 글자: recorder.steps가 준 ordinary 스텝의 text만 들고 있다. 다른 곳(알림·로그·출력 패널)에 쓰지 않는다
import type { daemonRpc } from "@kookabug/schema";
import { create } from "zustand";
import type { KookabugBridge } from "../../preload/bridge";
import { client, toRpcError } from "../rpc/client";
import { closeTab, openRecTab, REC_TAB_PATH } from "../store/tabs";
import { LIVE_STATES, recorderErrorText, SESSION_STATES, type RecorderStateResult, type RecorderStep } from "./labels";

export type RecorderOptions = Required<daemonRpc.RecorderOptions>;
export type SecretKeyInfo = daemonRpc.SecretKeyInfo;
export type WindowInfo = daemonRpc.WindowInfo;

export const DEFAULT_OPTIONS: RecorderOptions = { wait_as_appear: true, crop_targets: true };

export interface RecorderNotice {
  tone: "info" | "error";
  text: string;
  /** 강조할 스텝 (커밋 거부 data.steps) */
  steps: string[];
}

interface RecorderStoreState {
  /** 마지막으로 받은 녹화 상태 (없으면 아직 모름) */
  state: RecorderStateResult | null;
  /** state를 받은 때 (Date.now, 경과 시간 계산) */
  stateAt: number;
  steps: RecorderStep[];
  rev: number;
  /** 사이드바에서 고른 스텝 (REC 탭 정지 화면) */
  selected: string | null;
  options: RecorderOptions;
  secrets: SecretKeyInfo[];
  envNote: string | null;
  notice: RecorderNotice | null;
  /** 진행 중인 동작 (단추 끄기) */
  busy: string | null;
  windows: WindowInfo[] | null;
  /** 커밋 끝 결과 (사이드바 "F5로 바로 재생") */
  committed: { graph: string; warnings: string[] } | null;
  /** REC 탭이 확인 넣기 영역을 기다리는 중 */
  checkMode: "visible" | "text" | null;
  /** 워크스페이스 기록 가림 (U16 메모 뒤 절) */
  redactSecrets: boolean;
  /** 저장에 실패한 삽입을 되돌리지 못함: 같은 녹화를 다시 넣지 않는다 (B5 검수 H1) */
  retryBlocked: boolean;
  /** 변환 옵션을 서버 값으로 받은 세션 (그 뒤 사람이 바꾼 옵션을 상태 갱신이 덮지 않게, B5 검수 M3) */
  optionsSession: string | null;
  /**
   * 값 확인 스텝의 적용 안 한 기댓값 (스텝 → 글). 속성 탭(UX6)이 오른쪽 탭 전환·접기로 사라져도 남는다.
   * 적용 성공·스텝 삭제·세션이 끝나거나 바뀌면 지운다
   */
  expectedDrafts: Readonly<Record<string, string>>;
}

const NO_DRAFTS: Readonly<Record<string, string>> = {};

/**
 * 초안 세대: 녹화 세션이 끝나거나 바뀔 때·resetRecorder 때 올린다. 스텝 ID는 세션마다 rs1부터 다시 쓰므로 늦게 온 글자 읽기·적용
 * 응답이 다른 녹화의 같은 ID 초안을 바꾸지 않게 요청 때의 세대·세션을 대조한다 (UX6 검수 2 High)
 */
let draftGen = 0;

export const useRecorder = create<RecorderStoreState>(() => ({
  state: null,
  stateAt: 0,
  steps: [],
  rev: -1,
  selected: null,
  options: DEFAULT_OPTIONS,
  secrets: [],
  envNote: null,
  notice: null,
  busy: null,
  windows: null,
  committed: null,
  checkMode: null,
  redactSecrets: false,
  retryBlocked: false,
  optionsSession: null,
  expectedDrafts: NO_DRAFTS,
}));

// globalThis: 주 프로세스 검사(tsconfig.node, DOM 없음)도 이 파일을 타입 검사한다 (rpc/client.ts와 같음)
const app = () => (globalThis as unknown as { kookabug: KookabugBridge }).kookabug.app;

/** 지금 상태 (소유 연결이고 세션이 있음) */
export function ownedSession(s: Pick<RecorderStoreState, "state"> = useRecorder.getState()): boolean {
  return s.state !== null && s.state.owned && SESSION_STATES.has(s.state.state);
}

/** 녹화 중이라 실행을 막는다 (소유든 다른 창이든 — daemon이 recording_active로 거부한다) */
export function recordingBlocksRun(s: RecorderStateResult | null): boolean {
  return s !== null && LIVE_STATES.has(s.state);
}

/** 경과 시간 (녹화 중이면 받은 뒤 흐른 시간을 더한다) */
export function elapsedNow(s: Pick<RecorderStoreState, "state" | "stateAt">, now: number): number {
  const base = s.state?.elapsed_ms ?? 0;
  return s.state?.state === "recording" ? base + Math.max(0, now - s.stateAt) : base;
}

function setState(state: RecorderStateResult): void {
  // 세션이 끝나면 REC 탭도 닫는다 (2.11)
  if (!(state.owned && SESSION_STATES.has(state.state))) closeTab(REC_TAB_PATH);
  const prev = useRecorder.getState().state;
  const inSession = state.owned && SESSION_STATES.has(state.state);
  // 세션이 끝나거나 바뀌면 초안 세대를 올린다: 그 전 세션에서 보낸 읽기·적용 응답은 초안을 건드리지 않는다
  if (!inSession || (prev?.session ?? null) !== (state.session ?? null)) draftGen++;
  useRecorder.setState((s) => ({
    state,
    stateAt: Date.now(),
    // 세션이 끝나면 스텝·고름·확인 모드를 비운다 (글자를 들고 있지 않게)
    ...(state.owned && SESSION_STATES.has(state.state)
      ? {}
      : { steps: [], rev: -1, selected: null, checkMode: null, expectedDrafts: NO_DRAFTS }),
    ...(s.state?.session !== undefined && state.session !== undefined && s.state.session !== state.session
      ? { committed: null, expectedDrafts: NO_DRAFTS }
      : {}),
  }));
  // 변환 옵션은 커밋 때 적용하므로 녹화 뒤에 바꿀 수 있다: 새 세션을 처음 받을 때만 서버 값을 쓴다
  const session = state.session ?? null;
  if (state.options !== undefined && state.owned && session !== null && session !== useRecorder.getState().optionsSession) {
    useRecorder.setState({ options: { ...DEFAULT_OPTIONS, ...state.options }, optionsSession: session, retryBlocked: false });
  }
}

function fail(err: unknown, prefix = ""): void {
  const e = toRpcError(err);
  const data = e.data as { steps?: unknown } | undefined;
  const steps = Array.isArray(data?.steps) ? data.steps.filter((x): x is string => typeof x === "string") : [];
  useRecorder.setState({ notice: { tone: "error", text: `${prefix}${recorderErrorText(e.kind, e.message)}`, steps } });
}

export function dismissNotice(): void {
  useRecorder.setState({ notice: null });
}

// ── 따라가기 ────────────────────────────────────────────────────

let refreshTimer: ReturnType<typeof setTimeout> | null = null;
let refreshSeq = 0;

export async function refreshState(): Promise<void> {
  const seq = ++refreshSeq;
  try {
    const state = await client().call("recorder.state", {});
    if (seq !== refreshSeq) return;
    setState(state);
    if (state.owned && SESSION_STATES.has(state.state)) await refreshSteps();
  } catch {
    // 연결 없음: 다시 붙으면 다시 읽는다
  }
}

export async function refreshSteps(): Promise<void> {
  try {
    const r = await client().call("recorder.steps", {});
    // 스텝 하나를 고쳐도 다른 스텝(재검사)이 바뀔 수 있어 판이 같아도 목록을 통째로 바꾼다
    useRecorder.setState({ steps: r.steps, rev: r.rev });
  } catch {
    // 세션이 끝났거나 다른 연결: 상태 알림이 정리한다
  }
}

/** recorder.changed: 묶어서 상태·스텝을 다시 읽는다 */
export function onRecorderChanged(p: { state: string; rev?: number; session?: string }): void {
  const cur = useRecorder.getState().state;
  // 알림의 state를 바로 비추는 것은 같은 세션일 때만 — 지난 세션의 늦은 알림이 지금 녹화 상태를 덮지 않게 (SECFIX 3).
  // 다른 세션이면 아래 recorder.state로 daemon의 지금 상태를 다시 읽는다
  const sameSession = cur !== null && (p.session === undefined || cur.session === undefined || p.session === cur.session);
  if (cur !== null && sameSession && cur.state !== p.state) useRecorder.setState({ state: { ...cur, state: p.state as RecorderStateResult["state"] } });
  if (refreshTimer !== null) clearTimeout(refreshTimer);
  refreshTimer = setTimeout(() => {
    refreshTimer = null;
    void refreshState();
  }, 60);
}

export function resetRecorder(): void {
  closeTab(REC_TAB_PATH);
  draftGen++;
  useRecorder.setState({
    retryBlocked: false,
    optionsSession: null,
    state: null,
    steps: [],
    rev: -1,
    selected: null,
    notice: null,
    busy: null,
    windows: null,
    committed: null,
    checkMode: null,
    expectedDrafts: NO_DRAFTS,
  });
}

// ── 시작·정지 ───────────────────────────────────────────────────

export async function loadWindows(): Promise<void> {
  try {
    const r = await client().call("windows.list", {});
    useRecorder.setState({ windows: r.windows });
  } catch (err) {
    useRecorder.setState({ windows: [] });
    fail(err, "창 목록을 읽지 못했어요: ");
  }
}

async function busy<T>(name: string, fn: () => Promise<T>): Promise<T | undefined> {
  if (useRecorder.getState().busy !== null) return undefined;
  useRecorder.setState({ busy: name });
  try {
    return await fn();
  } finally {
    useRecorder.setState({ busy: null });
  }
}

/**
 * 녹화 시작 (2.9 시작 순서): 단축키 등록 → recorder.start. 등록이 실패하면 recorder.start를 보내지 않는다.
 * 앞 세션이 stopped로 남아 있으면 버리고 시작한다(사람이 "새 녹화"를 눌렀다)
 */
export async function startRecording(target: { window: number } | { launch: true }): Promise<boolean> {
  const result = await busy("start", async () => {
    useRecorder.setState({ notice: null, committed: null });
    const armed = await app().recorderArm();
    if (!armed.ok) {
      useRecorder.setState({ notice: { tone: "error", text: armed.message, steps: [] } });
      return false;
    }
    try {
      const params: daemonRpc.RecorderStartParams = {
        hotkeys: armed.hotkeys,
        options: useRecorder.getState().options,
        ...("window" in target ? { window: target.window } : { launch: {} }),
      };
      const state = await client().call("recorder.start", params);
      setState(state);
      // REC 탭: 녹화 중 지금 화면 (스텝을 고르면 그 정지 화면)
      openRecTab(state.window?.title ?? null);
      await refreshSteps();
      return true;
    } catch (err) {
      // 주 프로세스 문지기가 이미 풀었지만, 렌더러 쪽 실패(보내기 전)도 같은 결과가 되게 한 번 더
      await app().recorderDisarm();
      fail(err, "녹화를 시작하지 못했어요: ");
      return false;
    }
  });
  return result === true;
}

async function sessionCall(method: "recorder.pause" | "recorder.resume" | "recorder.stop" | "recorder.discard"): Promise<void> {
  await busy(method, async () => {
    try {
      setState(await client().call(method, {}));
      if (method !== "recorder.discard") await refreshSteps();
    } catch (err) {
      fail(err);
      await refreshState();
    }
  });
}

export const pauseRecording = () => sessionCall("recorder.pause");
export const resumeRecording = () => sessionCall("recorder.resume");
export const stopRecording = () => sessionCall("recorder.stop");
export const discardRecording = () => sessionCall("recorder.discard");

// ── 스텝 고치기 ─────────────────────────────────────────────────

/** step.update 결과로 그 스텝을 바꾼다 (지웠으면 뺀다) */
export function replaceStepFromServer(id: string, step: RecorderStep | null, rev: number): void {
  useRecorder.setState((s) => ({
    rev,
    steps: step === null ? s.steps.filter((x) => x.step !== id) : s.steps.map((x) => (x.step === id ? step : x)),
    selected: step === null && s.selected === id ? null : s.selected,
    ...(step === null && id in s.expectedDrafts ? { expectedDrafts: withoutDraft(s.expectedDrafts, id) } : {}),
  }));
}

function withoutDraft(drafts: Readonly<Record<string, string>>, step: string): Readonly<Record<string, string>> {
  const next = { ...drafts };
  delete next[step];
  return next;
}

/** 값 확인 기댓값 초안 (null = 지우기 — 서버 값으로 돌아간다) */
export function setExpectedDraft(step: string, text: string | null): void {
  useRecorder.setState((s) => ({
    expectedDrafts: text === null ? withoutDraft(s.expectedDrafts, step) : { ...s.expectedDrafts, [step]: text },
  }));
}

/** 초안 요청 표: 요청을 보낸 때의 세대·세션·스텝 */
export interface DraftTicket {
  gen: number;
  session: string | null;
  step: string;
}

export function draftTicket(step: string): DraftTicket {
  return { gen: draftGen, session: useRecorder.getState().state?.session ?? null, step };
}

/** 요청을 보낸 녹화가 아직 지금 녹화이고 그 스텝이 남아 있는가 */
export function draftTicketLive(t: DraftTicket): boolean {
  const s = useRecorder.getState();
  return t.gen === draftGen && t.session === (s.state?.session ?? null) && s.steps.some((x) => x.step === t.step);
}

/** 글자 읽기로 채우기 응답: 같은 녹화일 때만 초안에 쓴다 */
export function fillExpectedDraft(t: DraftTicket, text: string): boolean {
  if (!draftTicketLive(t)) return false;
  setExpectedDraft(t.step, text);
  return true;
}

/**
 * 기댓값 적용: 성공하면 초안을 지운다 (거부면 남겨 고칠 수 있게). 늦은 응답이 다른 녹화의 같은 ID 초안을 지우지 않게 같은 녹화일
 * 때만, 그리고 요청 중에 고친 글은 남기게 보낸 글과 지금 초안이 같을 때만 지운다
 */
export async function applyExpected(step: string, value: string): Promise<boolean> {
  const ticket = draftTicket(step);
  const done = await updateStep(step, { equals: value });
  if (done === false) return false;
  if (draftTicketLive(ticket) && useRecorder.getState().expectedDrafts[step] === value) setExpectedDraft(step, null);
  return true;
}

/** recorder.step.update. 거부(secret_region_overlap 등)는 띠에 보이고 false */
export async function updateStep(step: string, patch: daemonRpc.RecorderStepPatch): Promise<RecorderStep | null | false> {
  try {
    const r = await client().call("recorder.step.update", { step, patch });
    replaceStepFromServer(step, r.step, r.rev);
    const notice = useRecorder.getState().notice;
    if (notice !== null && notice.steps.includes(step)) useRecorder.setState({ notice: null });
    return r.step;
  } catch (err) {
    fail(err);
    // 바꾼 내용은 daemon 메모리에 반영됐다(임시 파일 정리만 실패) — 화면도 맞춘다
    if (toRpcError(err).kind === "recorder_store_unclean") await refreshSteps();
    return false;
  }
}

export function selectStep(step: string | null): void {
  useRecorder.setState({ selected: step, checkMode: null });
}

export function setOption(key: keyof RecorderOptions, on: boolean): void {
  useRecorder.setState((s) => ({ options: { ...s.options, [key]: on } }));
}

// ── 비밀값 ─────────────────────────────────────────────────────

export async function loadSecrets(): Promise<void> {
  try {
    const r = await client().call("secrets.list", {});
    useRecorder.setState({ secrets: r.keys, envNote: r.env_note });
  } catch {
    useRecorder.setState({ secrets: [] });
  }
}

/** 워크스페이스 record.redact_secrets (비밀값 스텝 메모 U16). 못 읽으면 꺼짐(기본) */
export async function loadRedactSetting(): Promise<void> {
  try {
    const r = await client().call("workspace.read", { path: "kookabug.json" });
    const config = JSON.parse(r.text) as { record?: { redact_secrets?: unknown } };
    useRecorder.setState({ redactSecrets: config.record?.redact_secrets === true });
  } catch {
    useRecorder.setState({ redactSecrets: false });
  }
}

/** "이 값으로 새 비밀값 만들기": 녹화 메모리의 원문을 자격 증명 관리자에 쓰고 그 키를 고른다 (값은 RPC로 보내지 않는다) */
export async function createSecret(step: string, key: string): Promise<boolean> {
  try {
    await client().call("secrets.create", { key, from_step: step });
    await Promise.all([refreshSteps(), loadSecrets()]);
    return true;
  } catch (err) {
    if (toRpcError(err).kind === "recorder_store_unclean") {
      // 비밀값은 만들어졌고 스텝도 바뀌었다 — 임시 파일 정리만 실패 (띠에 알리고 화면을 맞춘다)
      fail(err);
      await Promise.all([refreshSteps(), loadSecrets()]);
      return true;
    }
    fail(err, "비밀값을 만들지 못했어요: ");
    return false;
  }
}

// ── 확인 넣기 ───────────────────────────────────────────────────

export function beginCheck(kind: "visible" | "text" | null): void {
  useRecorder.setState({ checkMode: kind, selected: null });
}

/** 지금 화면(frame_id)의 영역을 화면 확인·값 확인 스텝으로 넣는다 */
export async function insertCheck(kind: "visible" | "text", frameId: string, rect: [number, number, number, number]): Promise<boolean> {
  try {
    const r = await client().call("recorder.insert_check", { kind, frame_id: frameId, rect });
    useRecorder.setState({ checkMode: null });
    await refreshSteps();
    if (r.step !== null) useRecorder.setState({ selected: r.step.step });
    return true;
  } catch (err) {
    fail(err);
    return false;
  }
}
