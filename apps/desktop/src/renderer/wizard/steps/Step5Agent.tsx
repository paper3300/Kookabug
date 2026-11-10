// 5단계 Agent (선택, 시안 Wizard5Agent): 감지한 CLI·직접 입력·API 키만(판단 노드 전용). 고르면 사용자 설정에 더하고
// 바로 연결 시험(주 프로세스 → `agent-job probe`). 시험 성공이면 "다음"이 켜진다. 권한 프리셋은 사용자 계층
// (마법사에는 읽기 전용·그래프 작성·지식 관리(추천)·전체만)
//
// 에이전트 패널의 "설정 도우미 열기"·"에이전트 설정…"도 이 단계만 연다(옛 첫 설정 대화 상자 대신, M8 R11). 그래서 저장은
// 패널과 같은 저장소 함수(agentStore.saveAgentSetup·setUserPreset)로 해 같은 revision을 쓴다. 감지 줄의 상태 글자도 패널과
// 같은 candidateStatus. 연결 시험은 무인 작업이 띄우는 본체 CLI(claude·codex)를 보므로 ACP 어댑터가 없어도 `cli_path`가
// 있으면 시험할 수 있다
//
// 합치기 검수(review_merge_1) 규칙:
// - 고른 에이전트 = 기본 에이전트(따로 고르는 칸 없음). 고를 때마다 그 순서대로 저장해 마지막에 고른 값이 남는다
// - 권한: 새 프로젝트 순서이면서 사용자 프리셋이 아직 없을 때만 curator 추천을 보이고 저장한다. 그 밖(only·short·이미
//   사용자 프리셋 있음)은 지금 실제 프리셋을 보이고, 사람이 바꿨을 때만 저장한다
// - 프리셋 저장은 화면이 읽은 revision 기준. 다른 곳에서 바뀌었으면 "다시 읽기" 안내(Conflict.tsx와 같은 방식)
// review_merge_2:
// - 연결 시험 중에도 줄은 고를 수 있고 고르면 저장 차례에 들어간다. 시험 결과는 시험한 에이전트 ID를 달고, 지금 선택과
//   같을 때만 "다음"이 켜진다. 앞 시험이 끝났을 때 선택이 바뀌었으면 그 결과는 버리고 지금 선택을 이어 시험한다
// - 다시 읽기가 실패하면 충돌·사람이 고른 값을 그대로 둔다
// review_merge_3 (경합을 구조로 없앤다):
// - 바쁠 때(에이전트 저장 중·"다음"·"저장" 콜백 중·충돌 중)는 줄·직접 입력·프리셋 고르기를 잠근다. 그래서 저장은 한 번에
//   하나이고, 진행 콜백이 시작할 때 읽은 선택·시험 결과는 끝날 때까지 바뀌지 않는다 (연결 시험 중 고르기는 그대로 된다)
// - 진행 콜백은 기본 에이전트를 확인만 한다: 지금 선택 = 이 앱이 자기 agents.set으로 마지막에 저장한 기본이고 그 뒤 자기
//   permissions.set만 이어졌을 때(ownDefaultSaved), 그리고 파일 revision이 저장 기준과 같을 때만 끝낸다
// - 에이전트 저장 충돌도 "다시 읽기" 전까지 막는다. 다시 읽으면 only는 파일의 기본을, new·short는 빈 선택을 보인다
import { useEffect, useRef, useState } from "react";
import {
  candidateStatus,
  checkUserRevision,
  effectivePreset,
  ownDefaultSaved,
  presetLabel,
  refreshCandidates,
  reloadUserSettings,
  USER_RELOAD_FAILED_TEXT,
  saveAgentSetup,
  setUserPreset,
  splitCommandLine,
  startSession,
  useAgent,
  type AgentCandidate,
  type AgentSpec,
} from "../../agent/agentStore";
import { SECURITY_BOUNDARY } from "../boundary";
import { ConflictNotice } from "../Conflict";
import { StepShell } from "../Wizard";
import { openAgentPanel } from "../../store/ui";
import { agentPresetPlan, agentStepReady, setAgent, setStepWarnings, setSummary, useWizard } from "../wizardStore";
import { appErrorText } from "./Step1Project";
import css from "../wizard.module.css";

type Candidate = AgentCandidate;
type Spec = AgentSpec;

const PRESETS: [string, string][] = [
  ["read_only", "읽기 전용"],
  ["graph_author", "그래프 작성"],
  ["curator", "지식 관리 · 추천"],
  ["full", "전체"],
];

const PRESET_TEXT: Record<string, string> = {
  read_only: "읽기 전용: 보기만 해요. 테스트·지식을 바꾸지 않아요.",
  graph_author: "그래프 작성: 테스트를 고칠 때마다 물어봐요.",
  curator: "지식 관리: 위키·사건을 쓰고 테스트를 실행해요. 게임을 직접 클릭할 땐 물어봐요.",
  full: "전체: 묻지 않고 모두 해요.",
};

/** 연결 시험 상태. `agentId` = 시험한 에이전트 (지금 선택과 다르면 "다음"을 켜지 않는다) */
type Probe =
  | { state: "idle" }
  | { state: "running"; agentId: string; name: string; started: number }
  | { state: "ok"; agentId: string; name: string; seconds: number }
  | { state: "fail"; agentId: string; name: string; code: string; text: string };

const PROBE_FAIL: Record<string, string> = {
  agent_job_unsupported: "무인 작업(agent-job)은 Claude Code·Codex CLI만 지원해요",
  cli_not_found: "실행 파일을 PATH에서 찾지 못했어요",
  job_active: "다른 작업이 도는 중이라 시험하지 못했어요",
  unknown_agent: "사용자 설정에 없는 Agent예요",
};

/** 감지 표 ID로 연결 시험 줄의 실행 파일 이름 */
function initial(name: string): string {
  return name.trim().charAt(0).toUpperCase() || "?";
}

export function Step5Agent() {
  const agent = useWizard((s) => s.agent);
  const mode = useWizard((s) => s.progress.mode);
  const onlyMode = mode === "only";
  const candidates = useAgent((s) => s.candidates) ?? [];
  const agents = useAgent((s) => s.agents);
  const defaultAgent = useAgent((s) => s.defaultAgent);
  const agentsProblem = useAgent((s) => s.agentsProblem);
  const permissions = useAgent((s) => s.permissions);
  const userConflict = useAgent((s) => s.userConflict);
  const [choice, setChoiceState] = useState<string | null>(agent?.id ?? null);
  const [manualName, setManualName] = useState("");
  const [manualLine, setManualLine] = useState("");
  /** 사람이 고른 프리셋 (null = 건드리지 않음) */
  const [preset, setPreset] = useState<string | null>(null);
  const [probe, setProbeState] = useState<Probe>(agent?.probed === true ? { state: "ok", agentId: agent.id, name: agent.name, seconds: 0 } : { state: "idle" });
  const [error, setError] = useState<string | null>(null);
  /** 에이전트 저장·진행 콜백이 도는 중 (줄 고르기를 잠근다) */
  const [busy, setBusy] = useState(false);
  const probing = useRef(false);
  /** 시험 중에 고른 다음 시험 대상 (앞 시험이 끝나면 이어 시험한다) */
  const pending = useRef<Spec | null>(null);
  const picked = useRef(false);
  /** 지금 선택 (비동기 콜백이 끝났을 때 선택이 바뀌었는지 본다) */
  const latest = useRef<string | null>(choice);
  /** 지금 시험 결과 (진행 콜백이 시작할 때 읽는다) */
  const probeNow = useRef<Probe>(probe);
  /** 잠금 겹 수 (저장·진행 콜백이 겹칠 수 있다) */
  const lock = useRef(0);
  /** 도는 에이전트 저장 (한 번에 하나) */
  const saving = useRef<Promise<boolean> | null>(null);

  const setProbe = (p: Probe | ((p: Probe) => Probe)) => {
    probeNow.current = typeof p === "function" ? p(probeNow.current) : p;
    setProbeState(probeNow.current);
  };

  /** 줄·직접 입력·프리셋을 고를 수 없는 때 (저장 중·진행 콜백 중·충돌 중) */
  const locked = () => lock.current > 0 || useAgent.getState().userConflict;

  const withLock = async <T,>(job: () => Promise<T>): Promise<T> => {
    lock.current += 1;
    setBusy(true);
    try {
      return await job();
    } finally {
      lock.current -= 1;
      setBusy(lock.current > 0);
    }
  };

  /** 줄 고르기. 잠겨 있으면 false (아무것도 바꾸지 않는다) */
  const setChoice = (id: string): boolean => {
    if (locked()) return false;
    picked.current = true;
    latest.current = id;
    setChoiceState(id);
    return true;
  };

  useEffect(() => {
    // 패널과 같은 저장소를 새로 읽는다 (패널에서 그 사이 바꿨을 수 있다). 이 화면의 저장 기준이 된다
    void reloadUserSettings();
    void refreshCandidates();
  }, []);

  // only 모드: 지금 기본 에이전트를 고른 줄로 보인다 (고른 에이전트 = 기본 에이전트). 사람이 고르기 전까지만
  useEffect(() => {
    if (!onlyMode || picked.current || choice !== null || defaultAgent === null) return;
    if (agents.some((a) => a.id === defaultAgent)) {
      latest.current = defaultAgent;
      setChoiceState(defaultAgent);
    }
  }, [onlyMode, choice, defaultAgent, agents]);

  /** 도는 에이전트 저장이 끝날 때까지 기다린다 (저장 중에는 줄이 잠기므로 기다린 뒤에도 선택은 그대로다) */
  const waitSaving = async () => {
    for (let p = saving.current; p !== null; p = saving.current) await p;
  };

  /**
   * 고른 에이전트를 사용자 설정에 더하고 기본 에이전트로 한다. 이 앱이 이미 그 값으로 저장했으면 쓰지 않는다. 패널과 같은
   * 저장소 함수(saveAgentSetup)라 기준은 화면이 받아들인 revision이고, 충돌이면 쓰지 않는다
   */
  const ensureSaved = async (spec: Spec): Promise<boolean> => {
    // 기다릴 것이 없으면 await 없이 바로 잠근다 (고른 그 순간부터 다른 줄을 못 고르게)
    if (saving.current !== null) await waitSaving();
    if (ownDefaultSaved(spec.id)) return true;
    if (useAgent.getState().userConflict) return false;
    const run = withLock(async () => {
      const have = useAgent.getState().agents.some((a) => a.id === spec.id);
      const problem = await saveAgentSetup(have ? [] : [spec], spec.id, null);
      if (problem !== null) {
        // 충돌은 ConflictNotice가 보인다
        if (!useAgent.getState().userConflict) setError(`저장하지 못했어요: ${problem}`);
        return false;
      }
      return true;
    });
    const tracked: Promise<boolean> = run.finally(() => {
      if (saving.current === tracked) saving.current = null;
    });
    saving.current = tracked;
    return tracked;
  };

  const runProbe = async (spec: Spec) => {
    // 시험은 한 번에 하나 (첫 await 전에 잡는다). 시험 중에 고른 줄은 저장 차례에만 넣고, 앞 시험이 끝나면 이어 시험한다
    if (probing.current) {
      pending.current = spec;
      void ensureSaved(spec);
      return;
    }
    probing.current = true;
    try {
      let target: Spec | null = spec;
      while (target !== null) {
        pending.current = null;
        const applied = await probeOnce(target);
        // 시험을 기다리는 사이 pickRow가 바꿨을 수 있다 (TS는 위에서 넣은 null로 좁힌다)
        const after = pending.current as Spec | null;
        // 시험 중에 같은 줄을 다시 골랐고 그 결과가 반영됐으면 또 시험하지 않는다
        target = after !== null && !(applied && after.id === target.id) ? after : null;
      }
    } finally {
      probing.current = false;
      pending.current = null;
    }
  };

  /** 한 번 시험한다. 끝났을 때 선택이 그대로면 결과를 반영하고 true, 선택이 바뀌었으면 결과를 버리고 false */
  const probeOnce = async (spec: Spec): Promise<boolean> => {
    setError(null);
    if (!(await ensureSaved(spec))) return false;
    if (latest.current !== spec.id) return false;
    const started = Date.now();
    setProbe({ state: "running", agentId: spec.id, name: spec.name, started });
    setAgent({ id: spec.id, name: spec.name, probed: false, kind: "cli" });
    let result: Probe;
    try {
      const r = await window.kookabug.app.agentProbe(spec.id);
      if (r.ok) {
        result = { state: "ok", agentId: spec.id, name: spec.name, seconds: (Date.now() - started) / 1000 };
      } else {
        const code = String(r.error_code ?? r.code ?? r.state ?? "probe_failed");
        result = { state: "fail", agentId: spec.id, name: spec.name, code, text: PROBE_FAIL[code] ?? "Kookabug 도구 호출을 보지 못했어요" };
      }
    } catch (err) {
      const text = appErrorText(err);
      const code = /^([a-z_]+):/.exec(err instanceof Error ? err.message.replace(/^Error invoking remote method '[^']*': (\w*Error: )?/, "") : "")?.[1] ?? "probe_failed";
      result = { state: "fail", agentId: spec.id, name: spec.name, code, text: PROBE_FAIL[code] ?? text };
    }
    if (latest.current !== spec.id) {
      // 선택이 바뀌었다: 이 결과는 버린다 (보이던 "시험 중"만 지운다. 이어 시험하면 그 시험이 덮는다)
      setProbe((p) => (p.state === "running" && p.agentId === spec.id ? { state: "idle" } : p));
      return false;
    }
    setProbe(result);
    if (result.state === "ok") {
      setAgent({ id: spec.id, name: spec.name, probed: true, kind: "cli" });
      setStepWarnings(5, []);
    }
    return true;
  };

  /** only 모드: 고르면 저장만 한다 (연결 시험은 단추로, 선택) */
  const saveOnly = async (spec: Spec) => {
    setError(null);
    setProbe({ state: "idle" });
    if (await ensureSaved(spec)) setAgent({ id: spec.id, name: spec.name, probed: false, kind: "cli" });
  };

  /** 고른 줄: 새 프로젝트·짧은 마법사는 바로 연결 시험, only 모드는 저장 */
  const choose = (spec: Spec) => void (onlyMode ? saveOnly(spec) : runProbe(spec));

  const pickCandidate = (c: Candidate) => {
    if (!setChoice(c.id)) return;
    // 무인 작업은 본체 CLI를 띄운다: 본체(cli_path)도 연결 명령도 없으면 시험할 것이 없다
    if (!c.installed && c.cli_path === null) {
      setProbe({ state: "fail", agentId: c.id, name: c.name, code: "cli_not_found", text: `설치되지 않았어요 (${c.cli} 명령을 찾지 못함)` });
      return;
    }
    choose({ id: c.id, name: c.name, command: c.command, args: c.args });
  };

  const pickSaved = (a: Spec) => {
    if (!setChoice(a.id)) return;
    choose(a);
  };

  const addManual = () => {
    const argv = splitCommandLine(manualLine);
    if (manualName.trim() === "" || argv.length === 0) return;
    const id = `custom-${manualName.trim().toLowerCase().replace(/[^a-z0-9_.-]+/g, "-").replace(/^-+|-+$/g, "") || "agent"}`.slice(0, 64);
    if (!setChoice(id)) return;
    choose({ id, name: manualName.trim(), command: argv[0], args: argv.slice(1) });
  };

  const pickApiKey = () => {
    if (!setChoice("apikey")) return;
    setProbe({ state: "idle" });
    setAgent({ id: "apikey", name: "API 키만", probed: false, kind: "apikey" });
  };

  const userPreset = (permissions?.layers?.find((l) => l.layer === "user")?.permissions as { preset?: unknown } | null | undefined)?.preset;
  const plan = agentPresetPlan(mode, {
    userPreset: typeof userPreset === "string" ? userPreset : null,
    effective: effectivePreset(permissions),
    picked: preset,
  });

  const savePreset = async (): Promise<boolean> => {
    if (plan.save === null) return true;
    const problem = await setUserPreset(plan.save);
    if (problem !== null) {
      // 충돌은 ConflictNotice가 보인다 (다시 읽기 전까지 저장 단추가 꺼진다)
      if (!useAgent.getState().userConflict) setError(problem);
      return false;
    }
    return true;
  };

  /**
   * 진행 콜백 ("다음"·"저장"·"저장하고 연결"). 도는 동안 줄 고르기가 잠기므로 시작할 때 읽은 선택·시험 결과로 끝까지 간다.
   * 기본 에이전트는 확인만 한다 — 이 앱이 자기 쓰기로 저장한 기본이 지금 선택일 때만 끝낸다. 아직 저장하지 않은 선택이면
   * 화면 기준 revision으로 저장까지는 한다 (외부 변경이 있으면 충돌로 끝나지 않는다)
   */
  const progress = (connect: boolean): Promise<boolean> =>
    withLock(async () => {
      // 잠그기 전에 시작한 고르기 저장이 있으면 그 뒤에 (그 저장도 지금 선택의 것이다)
      await waitSaving();
      if (useAgent.getState().userConflict) return false;
      const id = latest.current;
      const tried = probeNow.current;
      const probed = id !== null && tried.state === "ok" && tried.agentId === id;
      if (id !== null && id !== "apikey") {
        // 새 프로젝트·짧은 마법사는 지금 선택을 시험해 통과했어야 한다
        if (!onlyMode && !probed) return false;
        if (!ownDefaultSaved(id)) {
          const spec = useAgent.getState().agents.find((a) => a.id === id);
          if (spec === undefined) {
            setError("고른 Agent가 사용자 설정에 없어요");
            return false;
          }
          if (!(await ensureSaved(spec)) || !ownDefaultSaved(id)) return false;
        }
        // 파일이 그 사이 다른 곳에서 바뀌었는지 (캐시·기준은 바꾸지 않고 읽어 보기만)
        const same = await checkUserRevision();
        if (same !== true) {
          if (same === null) setError(USER_RELOAD_FAILED_TEXT);
          return false;
        }
      }
      if (!(await savePreset())) return false;
      const label = PRESETS.find(([p]) => p === plan.shown)?.[1].replace(" · 추천", "") ?? presetLabel(plan.shown);
      if (id === "apikey") {
        setStepWarnings(5, ["agent_api_key_only"]);
        setSummary(5, `API 키만 · 판단 노드 전용 (Init 불가)`, true);
      } else {
        const name = useAgent.getState().agents.find((a) => a.id === id)?.name ?? agent?.name ?? "";
        setSummary(5, `${name} · ${label} · ${probed ? "시험 통과" : "저장"}`);
      }
      if (connect && id !== null && id !== "apikey") {
        openAgentPanel();
        void startSession(id);
      }
      return true;
    });

  const next = () => progress(false);

  /** 다시 읽기 성공: 사람이 고른 값을 비우고 파일의 지금 값으로 맞춘다 (외부 변경은 여기서만 받아들인다) */
  const adoptReload = () => {
    setPreset(null);
    const s = useAgent.getState();
    const id = onlyMode && s.defaultAgent !== null && s.agents.some((a) => a.id === s.defaultAgent) ? s.defaultAgent : null;
    picked.current = false;
    pending.current = null;
    latest.current = id;
    setChoiceState(id);
    // 시험 결과는 같은 에이전트일 때만 남긴다
    if (probeNow.current.state !== "idle" && probeNow.current.agentId !== id) setProbe({ state: "idle" });
    const kept = probeNow.current.state === "ok" && id !== null;
    const spec = s.agents.find((a) => a.id === id);
    setAgent(spec === undefined ? null : { id: spec.id, name: spec.name, probed: kept, kind: "cli" });
  };

  const savedOnly = agents.filter((a) => !candidates.some((c) => c.id === a.id));
  const chosenSpec = agents.find((a) => a.id === choice) ?? null;
  const step = agentStepReady(mode, { choice, saved: chosenSpec !== null, probed: probe.state === "ok" && probe.agentId === choice });
  // 다른 곳에서 설정이 바뀌었으면 "다시 읽기" 전까지 끝내지 않는다 (Step2·6·7·8과 같음). 저장·진행 중에도 끝내지 않는다
  const ready = { done: step.done && !userConflict && !busy, connect: step.connect && !userConflict && !busy };
  /** 줄·직접 입력·프리셋 고르기를 끈다 */
  const pickOff = busy || userConflict;

  return (
    <StepShell
      title="어떤 Agent와 일할까요?"
      lead="Agent가 게임 정보를 모으고, 테스트를 만들고, 실패 원인을 찾아요. 나중에 연결해도 돼요."
      primary={
        onlyMode
          ? { label: "저장하고 연결", enabled: ready.connect, run: () => progress(true) }
          : { label: "다음", enabled: ready.done, run: next }
      }
      {...(onlyMode ? { extra: { label: "저장", enabled: ready.done, run: () => progress(false) } } : {})}
      right={
        <>
          <div className={css.caption}>
            {onlyMode
              ? "고르면 사용자 설정에 저장해요. 연결 시험(무인 작업)은 선택이에요."
              : '고르면 바로 연결을 시험해요. 통과해야 "다음"이 켜져요.'}
          </div>
          {onlyMode && chosenSpec !== null && (
            <button
              type="button"
              className={css.small}
              data-part="probe-run"
              disabled={probe.state === "running" || pickOff}
              onClick={() => void runProbe(chosenSpec)}
            >
              연결 시험
            </button>
          )}
          <div className={css.card} data-part="probe-card" data-state={probe.state}>
            <div className={css.cardHead}>
              연결 시험{probe.state !== "idle" ? ` · ${probe.name}` : ""}
              <small>{probe.state === "ok" ? `${probe.seconds.toFixed(1)}초` : probe.state === "running" ? "시험 중…" : ""}</small>
            </div>
            {probe.state === "idle" && <div className={css.cardRow}>Agent를 고르면 시작해요</div>}
            {probe.state !== "idle" && (
              <>
                <div className={css.cardRow}>
                  <span className={css.mark} data-state={probe.state === "fail" && probe.code === "cli_not_found" ? "fail" : probe.state === "running" ? "wait" : "ok"}>
                    {probe.state === "fail" && probe.code === "cli_not_found" ? "✕" : probe.state === "running" ? "…" : "✓"}
                  </span>
                  <span>
                    실행 파일 찾음<small>사용자 설정의 명령</small>
                  </span>
                </div>
                <div className={css.cardRow}>
                  <span className={css.mark} data-state={probe.state === "ok" ? "ok" : probe.state === "running" ? "wait" : "fail"}>
                    {probe.state === "ok" ? "✓" : probe.state === "running" ? "…" : "✕"}
                  </span>
                  <span>
                    Kookabug 도구 연결<small>무인 작업 안에서 kb_project_info 호출</small>
                  </span>
                </div>
              </>
            )}
            {probe.state === "ok" && <div className={css.band}>연결됐어요. 다음으로 넘어갈 수 있어요.</div>}
            {probe.state === "fail" && (
              <div className={css.band} data-tone="fail" data-part="probe-fail" data-code={probe.code}>
                {probe.text}
              </div>
            )}
          </div>
          <div className={css.caption}>{SECURITY_BOUNDARY}</div>
        </>
      }
    >
      <div className={css.list} role="radiogroup" aria-label="Agent" data-part="agent-list">
        {candidates.map((c) => {
          const status = candidateStatus(c);
          return (
            <label key={c.id} className={css.row} data-selected={choice === c.id} data-agent={c.id} data-tone={status.tone}>
              <span className={css.avatar} aria-hidden="true">
                {initial(c.name)}
              </span>
              <span className={css.rowText}>
                <span className={css.rowTitle}>
                  {c.name}
                  {(c.installed || c.cli_path !== null) && <span className={css.tag}>감지됨</span>}
                  {choice === c.id && probe.state === "ok" && probe.agentId === c.id && <span className={css.tag}>연결 시험 통과</span>}
                </span>
                <span className={css.rowSub} title={status.text}>
                  {status.text}
                </span>
              </span>
              <input type="radio" name="agent" checked={choice === c.id} disabled={pickOff} onChange={() => pickCandidate(c)} />
            </label>
          );
        })}
        {savedOnly.map((a) => (
          <label key={a.id} className={css.row} data-selected={choice === a.id} data-agent={a.id}>
            <span className={css.avatar} aria-hidden="true">
              {initial(a.name)}
            </span>
            <span className={css.rowText}>
              <span className={css.rowTitle}>
                {a.name}
                {choice === a.id && probe.state === "ok" && probe.agentId === a.id && <span className={css.tag}>연결 시험 통과</span>}
              </span>
              <span className={css.rowSub}>사용자 설정</span>
            </span>
            <input type="radio" name="agent" checked={choice === a.id} disabled={pickOff} onChange={() => pickSaved(a)} />
          </label>
        ))}
        <label className={css.row} data-selected={choice === "manual"}>
          <span className={css.avatar} aria-hidden="true">
            +
          </span>
          <span className={css.rowText}>
            <span className={css.rowTitle}>직접 입력</span>
            <span className={css.rowSub}>이름과 명령줄로 Agent 추가</span>
          </span>
          <input type="radio" name="agent" checked={choice === "manual"} disabled={pickOff} onChange={() => setChoice("manual")} />
        </label>
        <label className={css.row} data-selected={choice === "apikey"} data-agent="apikey">
          <span className={css.avatar} aria-hidden="true">
            ⚿
          </span>
          <span className={css.rowText}>
            <span className={css.rowTitle}>
              API 키만 <span className={css.tag} data-tone="warn">판단 노드 전용</span>
            </span>
            <span className={css.rowSub}>Init·조사·수리는 못 해요</span>
          </span>
          <input type="radio" name="agent" checked={choice === "apikey"} disabled={pickOff} onChange={pickApiKey} />
        </label>
      </div>
      {choice === "manual" && (
        <div className={css.inputRow}>
          <input className={css.input} placeholder="이름" aria-label="Agent 이름" value={manualName} disabled={pickOff} onChange={(e) => !locked() && setManualName(e.target.value)} />
          <input className={`${css.input} ${css.mono}`} placeholder="명령줄" aria-label="Agent 명령줄" value={manualLine} disabled={pickOff} onChange={(e) => !locked() && setManualLine(e.target.value)} />
          <button type="button" className={css.small} disabled={pickOff} onClick={addManual}>
            {onlyMode ? "추가" : "추가·시험"}
          </button>
        </div>
      )}
      {agents.length >= 2 && <span className={css.hint}>고른 Agent가 기본이에요. 에이전트 패널이 처음 연결하는 Agent예요.</span>}
      {agentsProblem !== null && (
        <p role="alert" className={css.error}>
          사용자 설정을 읽지 못했어요: {agentsProblem}
        </p>
      )}
      <div className={css.field}>
        <span className={css.fieldLabel}>Agent 권한</span>
        <div className={css.seg} role="group" aria-label="Agent 권한">
          {PRESETS.map(([value, label]) => (
            <button key={value} type="button" aria-pressed={plan.shown === value} disabled={pickOff} onClick={() => !locked() && setPreset(value)}>
              {label}
            </button>
          ))}
        </div>
        <span className={css.hint} data-part="preset-hint" data-preset={plan.shown}>
          {PRESET_TEXT[plan.shown] ?? `지금: ${presetLabel(plan.shown)} (설정 > 권한에서 정한 값)`}
          <br />
          혼자 도는 작업은 7단계 자동화 정책을 따라요.
        </span>
      </div>
      {userConflict && (
        <ConflictNotice
          onReload={() => {
            setError(null);
            // 읽기가 성공한 뒤에만 사람이 고른 값을 비운다 (실패면 충돌·고른 값이 그대로 남는다)
            void reloadUserSettings().then((ok) => {
              if (ok) adoptReload();
              else setError(USER_RELOAD_FAILED_TEXT);
            });
          }}
        />
      )}
      {error !== null && (
        <p role="alert" className={css.error}>
          {error}
        </p>
      )}
    </StepShell>
  );
}
