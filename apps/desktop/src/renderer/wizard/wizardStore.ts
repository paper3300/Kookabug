// 첫 프로젝트 설정 마법사 상태 (M8 계획 3.17, KB문서 13장). 단계 진행·완료 조건·건너뛰기·이어서·짧은 마법사 판정은
// 순수 함수로 두고(wizardStore.test.ts), 저장소는 그 결과만 들고 있다.
//
// 진행 저장: 1단계(프로젝트 생성) 뒤에는 `.kookabug/wizard.json`(`wizard.set`, 단계 상태만), 그 전에는 메모리.
// 입력 값(경로·이름·비밀값)은 여기 두지 않는다 — 각 단계가 RPC로 바로 쓰고 "됐다"만 표시한다
import { create } from "zustand";
import { client, toRpcError } from "../rpc/client";

export type StepNo = 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9;
export type Storage = "team" | "pc" | "user" | "credential";

export interface StepInfo {
  n: StepNo;
  title: string;
  required: boolean;
  storage: Storage[];
}

/** KB문서 13장 표 (필수 = 완료 조건을 채워야 "다음", 선택 = "건너뛰기" 있음) */
export const STEPS: readonly StepInfo[] = [
  { n: 0, title: "시작", required: false, storage: [] },
  { n: 1, title: "프로젝트", required: true, storage: ["team"] },
  { n: 2, title: "게임", required: true, storage: ["pc", "team"] },
  { n: 3, title: "환경 점검", required: true, storage: [] },
  { n: 4, title: "테스트 계정", required: false, storage: ["credential"] },
  { n: 5, title: "Agent", required: false, storage: ["user"] },
  { n: 6, title: "프로젝트 정보", required: false, storage: ["team", "pc"] },
  { n: 7, title: "자동화 정책", required: true, storage: ["team"] },
  { n: 8, title: "기록", required: true, storage: ["team"] },
  { n: 9, title: "완료", required: false, storage: [] },
];

/** 팀원용 짧은 마법사가 보는 이 PC·사용자 단계 (팀 설정 6~8은 이미 있다) */
export const SHORT_STEPS: readonly StepNo[] = [2, 3, 4, 5];
export const NEW_STEPS: readonly StepNo[] = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9];

export function stepInfo(n: number): StepInfo {
  return STEPS[n] ?? STEPS[0];
}

export function isOptional(n: number): boolean {
  return n === 4 || n === 5 || n === 6;
}

export interface Warning {
  step: number;
  code: string;
}

/** `.kookabug/wizard.json` (kookabug.wizard/0) */
export interface WizardFile {
  format: "kookabug.wizard/0";
  step: number;
  done: number[];
  skipped: number[];
  warnings: Warning[];
}

export type Mode = "new" | "short" | "only";

export interface Progress {
  mode: Mode;
  /** 이번에 거치는 단계 순서 */
  steps: StepNo[];
  step: StepNo;
  done: number[];
  skipped: number[];
  warnings: Warning[];
  /** 단계 하나만 다시 열었을 때 끝나면 돌아갈 단계 (9단계 "지금 연결" → 5 → 9) */
  returnTo: StepNo | null;
}

/** 단계 판정 재료 (wizard.get·secrets.list·agents.get) */
export interface SetupSnapshot {
  wizard: WizardFile | null;
  teamSetup: boolean;
  gameExecutable: string | null;
  gameTitle: string | null;
  secretKeys: number;
  /** 사용자 설정의 에이전트 수 (-1 = 못 읽음: 비었다고 보지 않는다) */
  agents: number;
}

/** 이 PC·사용자 단계 중 비어 있는 것 (3 점검은 이 PC 기록이 없으면 늘 빈 단계) */
export function emptyShortSteps(s: SetupSnapshot): StepNo[] {
  const empty: StepNo[] = [];
  if (s.gameExecutable === null) empty.push(2);
  if (s.wizard === null || !s.wizard.done.includes(3)) empty.push(3);
  if (s.secretKeys === 0) empty.push(4);
  if (s.agents === 0) empty.push(5);
  return empty;
}

/**
 * 프로젝트를 연 뒤 마법사를 자동으로 띄울지 (ShortWizardWatch):
 * - 이 PC에 진행이 있고 끝나지 않았으면 이어서 (1단계를 마쳤으면 새 프로젝트 순서, 아니면 짧은 마법사)
 * - 진행이 없고 팀 첫 설정을 마친 프로젝트(team_setup)면 빈 이 PC 단계만 짧은 마법사 (U8: 이 PC에서 처음 한 번)
 */
export function autoOpenPlan(s: SetupSnapshot): Progress | null {
  const plan = shortOrResumePlan(s);
  if (plan !== null) return plan;
  // 짧은 마법사가 뜨지 않을 때만: 사용자 설정에 에이전트가 없으면 5단계만 한 번 (2026-11-09 사용자 요청, M8 합치기 2).
  // "한 번" = 이 PC wizard.json에 5단계 완료·건너뜀이 없음 (닫으면 건너뜀으로 남는다 — closeWizard)
  const w = s.wizard;
  if (s.agents === 0 && w?.done.includes(5) !== true && w?.skipped.includes(5) !== true) return only(5, w);
  return null;
}

function shortOrResumePlan(s: SetupSnapshot): Progress | null {
  const w = s.wizard;
  if (w !== null) {
    if (w.done.includes(9)) return null;
    if (w.done.includes(1)) return resume(w, "new", NEW_STEPS);
    // 짧은 마법사는 팀 첫 설정을 마친 프로젝트만 (U8). 설정 도우미·에이전트 패널로 단계 하나만 열었다 닫은 기록은
    // 팀 설정 전 프로젝트에서 짧은 마법사를 자동으로 띄우지 않는다 (R11 자동 띄우기 중복 제거)
    if (!s.teamSetup) return null;
    const short =[...SHORT_STEPS.filter((n) => !w.done.includes(n) && !w.skipped.includes(n)), 9 as StepNo];
    return resume(w, "short", short);
  }
  if (!s.teamSetup) return null;
  const empty = emptyShortSteps(s);
  if (empty.length === 0) return null;
  return start("short", [...empty, 9]);
}

export function start(mode: Mode, steps: readonly StepNo[], from?: StepNo): Progress {
  return {
    mode,
    steps: [...steps],
    step: from ?? steps[0],
    done: [],
    skipped: [],
    warnings: [],
    returnTo: null,
  };
}

/** 저장된 진행에서 이어서 (저장된 단계가 순서에 없으면 순서의 첫 단계) */
export function resume(w: WizardFile, mode: Mode, steps: readonly StepNo[]): Progress {
  const step = (steps.includes(w.step as StepNo) ? w.step : steps[0]) as StepNo;
  return { mode, steps: [...steps], step, done: [...w.done], skipped: [...w.skipped], warnings: [...w.warnings], returnTo: null };
}

/** 단계 하나만 다시 연다 (설정 도우미·완료 화면의 건너뛴 단계) */
export function only(n: StepNo, base?: WizardFile | null): Progress {
  return {
    mode: "only",
    steps: [n],
    step: n,
    done: [...(base?.done ?? [])],
    skipped: [...(base?.skipped ?? [])],
    warnings: [...(base?.warnings ?? [])],
    returnTo: null,
  };
}

/** "다음"이 켜지는가: 필수 단계는 완료 조건(ready), 선택 단계도 "다음"은 ready일 때만 (건너뛰기는 따로) */
export function canAdvance(p: Progress, ready: boolean): boolean {
  if (p.step === 0) return false; // 0단계는 "새 / 열기"를 고르는 버튼으로만 넘어간다
  return ready;
}

export function canSkip(p: Progress): boolean {
  return isOptional(p.step);
}

function nextIn(p: Progress): StepNo | null {
  if (p.returnTo !== null) return p.returnTo;
  const i = p.steps.indexOf(p.step);
  return i >= 0 && i + 1 < p.steps.length ? p.steps[i + 1] : null;
}

function withStep(p: Progress, step: StepNo | null, finished: boolean): { progress: Progress; finished: boolean } {
  return { progress: { ...p, step: step ?? p.step, returnTo: step === p.returnTo ? null : p.returnTo }, finished: finished || step === null };
}

/** 완료하고 다음으로. 순서 끝이면 finished */
export function advance(p: Progress): { progress: Progress; finished: boolean } {
  const done = p.done.includes(p.step) ? p.done : [...p.done, p.step].sort((a, b) => a - b);
  const skipped = p.skipped.filter((n) => n !== p.step);
  return withStep({ ...p, done, skipped }, nextIn(p), false);
}

/** 선택 단계 건너뛰기 (완료 표시 없이 건너뜀 목록에 남는다 — 완료 화면·설정 도우미에서 다시 연다) */
export function skip(p: Progress): { progress: Progress; finished: boolean } {
  if (!canSkip(p)) return { progress: p, finished: false };
  const skipped = p.skipped.includes(p.step) ? p.skipped : [...p.skipped, p.step].sort((a, b) => a - b);
  const done = p.done.filter((n) => n !== p.step);
  return withStep({ ...p, done, skipped }, nextIn(p), false);
}

export function back(p: Progress): Progress {
  if (p.returnTo !== null) return { ...p, step: p.returnTo, returnTo: null };
  const i = p.steps.indexOf(p.step);
  // 1단계를 마친 뒤에는 0·1로 돌아가지 않는다 (프로젝트는 이미 만들었다)
  const floor = p.done.includes(1) ? p.steps.indexOf(2) : 0;
  return i > Math.max(0, floor) ? { ...p, step: p.steps[i - 1] } : p;
}

export function canGoBack(p: Progress): boolean {
  return back(p) !== p;
}

/** 단계의 경고를 바꾼다 (그 단계의 지난 경고는 지우고 새로) */
export function setWarnings(p: Progress, step: number, codes: readonly string[]): Progress {
  return { ...p, warnings: [...p.warnings.filter((w) => w.step !== step), ...codes.map((code) => ({ step, code }))] };
}

/** 닫을 때의 진행: only 모드에서 끝내지 않은 선택 단계는 건너뜀 (에이전트 5단계 자동 띄우기를 다시 하지 않게) */
export function closedProgress(p: Progress): Progress {
  if (p.mode !== "only" || !isOptional(p.step) || p.done.includes(p.step) || p.skipped.includes(p.step)) return p;
  return { ...p, skipped: [...p.skipped, p.step].sort((a, b) => a - b) };
}

/**
 * 5단계 Agent의 완료 판정. 새 프로젝트·짧은 마법사는 연결 시험(무인 작업 probe) 통과 또는 API 키만.
 * 단계 하나만 연 화면(only — 에이전트 패널·설정 도우미·자동 5단계)은 "저장됨"이면 끝낼 수 있고 시험은 선택이다
 * (ACP로만 붙는 에이전트도 저장하고 연결할 수 있게). connect = "저장하고 연결"이 켜지는가
 */
export function agentStepReady(
  mode: Mode,
  s: { choice: string | null; saved: boolean; probed: boolean },
): { done: boolean; connect: boolean } {
  if (s.choice === "apikey") return { done: true, connect: false };
  if (mode === "only") return { done: s.saved, connect: s.saved };
  return { done: s.probed, connect: false };
}

/** 5단계 마법사가 추천하는 권한 프리셋 */
export const RECOMMENDED_PRESET = "curator";

/**
 * 5단계 권한 프리셋: 보일 값(`shown`)과 끝낼 때 저장할 값(`save`, null = 저장 안 함).
 * 새 프로젝트 순서이면서 사용자 프리셋이 아직 없을 때만 추천(curator)을 보이고 고르지 않아도 저장한다. 그 밖(only·short·이미
 * 사용자 프리셋 있음)은 지금 실제 프리셋(`effective`)을 보이고, 사람이 다른 값을 골랐을 때(`picked`)만 저장한다
 */
export function agentPresetPlan(
  mode: Mode,
  s: { userPreset: string | null; effective: string; picked: string | null },
): { shown: string; save: string | null } {
  if (mode === "new" && s.userPreset === null) {
    const shown = s.picked ?? RECOMMENDED_PRESET;
    return { shown, save: shown };
  }
  const shown = s.picked ?? s.effective;
  return { shown, save: s.picked !== null && s.picked !== s.effective ? s.picked : null };
}

export function toFile(p: Progress): WizardFile {
  return { format: "kookabug.wizard/0", step: p.step, done: [...p.done], skipped: [...p.skipped], warnings: [...p.warnings] };
}

// ── 저장소 ─────────────────────────────────────────────────────

/** 9단계 요약에 보이는 한 줄씩 (값이 아니라 결과 글 — 경로·비밀값 없음) */
export type Summary = Partial<Record<number, { text: string; warn?: boolean }>>;

interface WizardStore {
  open: boolean;
  progress: Progress;
  /** 단계 완료 조건을 채웠다 (단계 컴포넌트가 정한다) */
  ready: Partial<Record<number, boolean>>;
  /** 워크스페이스가 열려 wizard.json에 쓸 수 있다 */
  persisted: boolean;
  summary: Summary;
  /** 5단계에서 고른 Agent (연결 시험 통과면 Init에 쓴다) */
  agent: { id: string; name: string; probed: boolean; kind: "cli" | "apikey" | "custom" } | null;
  saveError: string | null;
}

export const useWizard = create<WizardStore>(() => ({
  open: false,
  progress: start("new", NEW_STEPS),
  ready: {},
  persisted: false,
  summary: {},
  agent: null,
  saveError: null,
}));

async function persist(): Promise<void> {
  const s = useWizard.getState();
  if (!s.persisted) return;
  try {
    await client().call("wizard.set", { wizard: toFile(s.progress) });
    if (useWizard.getState().saveError !== null) useWizard.setState({ saveError: null });
  } catch (err) {
    useWizard.setState({ saveError: toRpcError(err).message });
  }
}

/** 시작 화면 "새 프로젝트 만들기": 1단계부터 (0단계 = 시작 화면의 두 갈래, "이전"으로 간다). 프로젝트가 생기기 전이라 메모리에만 */
export function openNewWizard(): void {
  useWizard.setState({
    open: true,
    progress: start("new", NEW_STEPS, 1),
    ready: {},
    persisted: false,
    summary: {},
    agent: null,
    saveError: null,
  });
}

/** 열린 프로젝트에서 마법사를 띄운다 (짧은 마법사·이어서·단계 하나) */
export function openWizardWith(progress: Progress): void {
  useWizard.setState({ open: true, progress, ready: {}, persisted: true, saveError: null });
}

export function setReady(step: number, ready: boolean): void {
  useWizard.setState((s) => (s.ready[step] === ready ? s : { ready: { ...s.ready, [step]: ready } }));
}

export function setSummary(step: number, text: string, warn = false): void {
  useWizard.setState((s) => ({ summary: { ...s.summary, [step]: { text, warn } } }));
}

export function setStepWarnings(step: number, codes: readonly string[]): void {
  useWizard.setState((s) => ({ progress: setWarnings(s.progress, step, codes) }));
}

export function setAgent(agent: WizardStore["agent"]): void {
  useWizard.setState({ agent });
}

/** 1단계에서 프로젝트를 만들었다: 이제부터 wizard.json에 남긴다 */
export function markPersisted(): void {
  useWizard.setState({ persisted: true });
}

export async function goNext(): Promise<boolean> {
  const { progress, ready } = useWizard.getState();
  if (!canAdvance(progress, ready[progress.step] === true)) return false;
  const r = advance(progress);
  useWizard.setState({ progress: r.progress });
  await persist();
  if (r.finished) useWizard.setState({ open: false });
  return r.finished;
}

export async function goSkip(): Promise<void> {
  const from = useWizard.getState().progress.step;
  const r = skip(useWizard.getState().progress);
  useWizard.setState({ progress: r.progress });
  // Agent를 건너뛰면 9단계에서 Init을 끄고 녹화를 기본으로 (KB문서 사용자 결정 3차 5)
  if (from === 5) useWizard.setState({ agent: null });
  await persist();
  if (r.finished) useWizard.setState({ open: false });
}

export async function goBack(): Promise<void> {
  useWizard.setState((s) => ({ progress: back(s.progress) }));
  await persist();
}

/** 9단계 "지금 연결": 5단계만 열고 끝나면 9단계로 */
export async function reopenStep(n: StepNo): Promise<void> {
  useWizard.setState((s) => ({ progress: { ...s.progress, step: n, returnTo: s.progress.step } }));
  await persist();
}

/** 0단계 "새 프로젝트" → 1단계 */
export function chooseNew(): void {
  useWizard.setState((s) => ({ progress: { ...s.progress, step: 1 } }));
}

/** 닫기: 진행은 wizard.json에 남는다 (다시 열면 이어서). 단계 하나만 연 화면(only)의 선택 단계는 건너뜀으로 남긴다 */
export async function closeWizard(): Promise<void> {
  useWizard.setState((s) => ({ progress: closedProgress(s.progress) }));
  await persist();
  useWizard.setState({ open: false });
}

/** 마지막 단계(9) 완료 표시 후 닫는다 */
export async function finishWizard(): Promise<void> {
  useWizard.setState((s) => ({
    progress: { ...s.progress, done: s.progress.done.includes(9) ? s.progress.done : [...s.progress.done, 9] },
  }));
  await persist();
  useWizard.setState({ open: false });
}

/** 프로젝트를 닫으면 마법사도 닫는다 (진행은 파일에 있다) */
export function resetWizard(): void {
  useWizard.setState({ open: false, ready: {}, persisted: false, summary: {}, agent: null, saveError: null });
}
