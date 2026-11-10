// 에이전트 첫 설정 대화 상자: 프로젝트를 열었는데 사용자 설정에 에이전트가 하나도 없으면 한 번 띄운다.
// 이 PC에서 찾은 에이전트(감지 표)를 고르고, 기본 에이전트와 권한 프리셋을 정해 사용자 설정에 저장한다.
// "나중에"를 누르면 앱 설정에 적어 다시 띄우지 않는다(에이전트 패널의 "설정 도우미 열기"로 다시 열 수 있다)
import { useEffect, useMemo, useRef, useState } from "react";
import { create } from "zustand";
import { openAgentPanel } from "../store/ui";
import { useWorkspace } from "../store/workspace";
import shell from "../app/shell.module.css";
import css from "./agent.module.css";
import {
  PRESETS,
  candidateStatus,
  effectivePreset,
  refreshCandidates,
  refreshPermissions,
  saveAgentSetup,
  startSession,
  useAgent,
  type AgentCandidate,
} from "./agentStore";

/** 앱 설정(userData/settings.json)의 "나중에" 표시. 못 읽으면 묻지 않는다 */
async function dismissed(): Promise<boolean> {
  try {
    return await window.kookabug.app.agentSetupDismissedGet();
  } catch {
    return true;
  }
}

function rememberDismiss(): void {
  void window.kookabug.app.agentSetupDismissedSet().catch(() => {});
}

export const useAgentSetup = create<{ open: boolean; shown: boolean }>(() => ({ open: false, shown: false }));

/** 에이전트 패널의 "설정 도우미" 단추 */
export function openAgentSetup(): void {
  useAgentSetup.setState({ open: true, shown: true });
}

function close(): void {
  useAgentSetup.setState({ open: false });
}

/** 프로젝트가 열려 있고 에이전트 설정을 읽었는데 비어 있으면 (앱 실행마다 한 번, "나중에" 전까지) 띄운다 */
function useAutoOpen(): void {
  const connected = useWorkspace((s) => s.daemon.status === "connected");
  const loaded = useAgent((s) => s.agentsLoaded);
  const empty = useAgent((s) => s.agents.length === 0 && s.agentsProblem === null);
  useEffect(() => {
    if (!connected || !loaded || !empty) return;
    if (useAgentSetup.getState().shown) return;
    useAgentSetup.setState({ shown: true });
    void dismissed().then((no) => {
      // 기다리는 동안 에이전트가 생겼거나 프로젝트를 닫았으면 띄우지 않는다
      const { agents } = useAgent.getState();
      if (!no && agents.length === 0 && useWorkspace.getState().root !== null) openAgentSetup();
    });
  }, [connected, loaded, empty]);
}

function SetupBox() {
  const candidates = useAgent((s) => s.candidates);
  const permissions = useAgent((s) => s.permissions);
  const configured = useAgent((s) => s.agents);
  const [picked, setPicked] = useState<Set<string> | null>(null);
  const [defaultId, setDefaultId] = useState<string | null>(null);
  const [preset, setPreset] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void refreshCandidates();
    void refreshPermissions();
  }, []);

  // 처음 받은 감지 결과로 기본 선택: 연결할 수 있는 것은 모두 고르고, 기본 에이전트는 그 첫째
  const usable = useMemo(() => (candidates ?? []).filter((c) => c.installed && !configured.some((a) => a.id === c.id)), [candidates, configured]);
  useEffect(() => {
    if (candidates === null || picked !== null) return;
    setPicked(new Set(usable.map((c) => c.id)));
    setDefaultId(usable[0]?.id ?? null);
  }, [candidates, usable, picked]);

  // 포커스를 대화 상자 안에 둔다: 주 단추 → 켜진 첫 칸 → 상자 자체 (밖으로 나가면 되돌린다, 뒤쪽이 키를 받지 않게)
  useEffect(() => {
    const box = boxRef.current;
    if (box === null) return;
    const first = () =>
      box.querySelector<HTMLElement>("[data-primary=true]:not(:disabled)") ??
      box.querySelector<HTMLElement>("button:not(:disabled), input:not(:disabled), select:not(:disabled)") ??
      box;
    if (!box.contains(document.activeElement)) first().focus();
    const keepInside = (e: FocusEvent) => {
      if (e.target instanceof Node && !box.contains(e.target)) first().focus();
    };
    document.addEventListener("focusin", keepInside);
    return () => document.removeEventListener("focusin", keepInside);
  }, [candidates]);

  const chosen: AgentCandidate[] = usable.filter((c) => picked?.has(c.id) === true);
  const currentPreset = preset ?? effectivePreset(permissions);
  const effectiveDefault = chosen.some((c) => c.id === defaultId) ? defaultId : (chosen[0]?.id ?? null);

  const toggle = (id: string) => {
    const next = new Set(picked ?? []);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setPicked(next);
  };

  const later = () => {
    rememberDismiss();
    close();
  };

  const save = async (connect: boolean) => {
    setBusy(true);
    setError(null);
    const problem = await saveAgentSetup(chosen, effectiveDefault, preset);
    setBusy(false);
    if (problem !== null) {
      setError(`저장하지 못했어요: ${problem}`);
      return;
    }
    close();
    if (connect && effectiveDefault !== null) {
      openAgentPanel();
      void startSession(effectiveDefault);
    }
  };

  return (
    <div className={shell.dialogBackdrop}>
      <div
        ref={boxRef}
        role="dialog"
        aria-modal="true"
        aria-label="에이전트 설정"
        className={`${shell.dialog} ${css.setupDialog}`}
        data-part="agent-setup"
        tabIndex={-1}
        onKeyDown={(e) => {
          e.stopPropagation();
          if (e.key === "Escape") {
            e.preventDefault();
            close();
          }
        }}
      >
        <div className={shell.dialogTitle}>에이전트 설정</div>
        <div className={shell.dialogMessage}>
          에이전트 CLI를 ACP로 붙이면 그래프 만들기·실패 분석·화면 탐색을 맡길 수 있어요. 이 PC에서 찾은 에이전트를 고르세요. 나중에 오른쪽
          에이전트 패널에서 바꿀 수 있어요.
        </div>
        <span className={css.sectionLabel}>찾은 에이전트</span>
        <div className={css.agentList}>
          {candidates === null && <div className={css.agentRow}>찾는 중…</div>}
          {(candidates ?? []).map((c) => {
            const status = candidateStatus(c);
            const already = configured.some((a) => a.id === c.id);
            const selectable = c.installed && !already;
            return (
              <div key={c.id} className={css.agentRow} data-part="setup-row" data-id={c.id} data-tone={status.tone}>
                <label className={css.setupPick}>
                  <input
                    type="checkbox"
                    aria-label={`${c.name} 사용`}
                    disabled={!selectable || busy}
                    checked={already || picked?.has(c.id) === true}
                    onChange={() => toggle(c.id)}
                  />
                  <span className={css.agentName}>
                    <b>{c.name}</b>
                    <small className={css.setupStatus} data-tone={status.tone} title={status.text}>
                      {already ? "이미 설정됨" : status.text}
                    </small>
                  </span>
                </label>
                {selectable && picked?.has(c.id) === true && (
                  <label className={css.setupDefault}>
                    <input type="radio" name="default-agent" checked={effectiveDefault === c.id} disabled={busy} onChange={() => setDefaultId(c.id)} />
                    기본
                  </label>
                )}
              </div>
            );
          })}
        </div>
        {candidates !== null && usable.length === 0 && (
          <div className={shell.dialogMessage} data-part="setup-none">
            지금 바로 연결할 수 있는 에이전트가 없어요. Claude Code나 Codex CLI를 설치·로그인하고 Node.js(npx)가 있으면 다시 열어 보세요. ACP로 말하는
            다른 에이전트는 에이전트 패널의 "직접 입력"으로 더할 수 있어요.
          </div>
        )}
        <label className={css.field}>
          에이전트 권한 (사용자 기본값)
          <select className={css.select} aria-label="권한 프리셋" value={currentPreset} disabled={busy} onChange={(e) => setPreset(e.target.value)}>
            {PRESETS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        {error !== null && (
          <div className={shell.dialogError} role="alert">
            {error}
          </div>
        )}
        <div className={shell.dialogButtons}>
          <button type="button" className={shell.dialogButton} disabled={busy} onClick={later} data-part="setup-later">
            나중에
          </button>
          <button
            type="button"
            className={shell.dialogButton}
            disabled={busy || (chosen.length === 0 && preset === null)}
            onClick={() => void save(false)}
            data-part="setup-save"
          >
            저장
          </button>
          <button
            type="button"
            className={shell.dialogPrimary}
            data-primary="true"
            disabled={busy || effectiveDefault === null}
            onClick={() => void save(true)}
            data-part="setup-connect"
          >
            {busy ? "저장 중…" : "저장하고 연결"}
          </button>
        </div>
      </div>
    </div>
  );
}

/** Shell에 한 번 둔다 */
export function AgentSetupDialog() {
  useAutoOpen();
  const open = useAgentSetup((s) => s.open);
  return open ? <SetupBox /> : null;
}
