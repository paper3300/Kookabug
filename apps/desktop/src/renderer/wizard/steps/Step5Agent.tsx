// 5단계 Agent (선택, 시안 Wizard5Agent): 감지한 CLI·직접 입력·API 키만(판단 노드 전용). 고르면 사용자 설정에 더하고
// (`agents.set`) 바로 연결 시험(주 프로세스 → `agent-job probe`). 시험 성공이면 "다음"이 켜진다. 권한 프리셋은
// 사용자 계층 `permissions.set` (마법사에는 읽기 전용·그래프 작성·지식 관리(추천)·전체만)
//
// 합친 뒤(8장): main의 AgentSetupDialog·agentStore.saveAgentSetup·Picker를 쓰도록 바꾼다. 지금은 m8에 있는 RPC만 쓴다
import type { ResultOf } from "@kookabug/schema";
import { useEffect, useRef, useState } from "react";
import { refreshAgents, refreshPermissions, splitCommandLine } from "../../agent/agentStore";
import { client, toRpcError } from "../../rpc/client";
import { SECURITY_BOUNDARY } from "../boundary";
import { StepShell } from "../Wizard";
import { setAgent, setStepWarnings, setSummary, useWizard } from "../wizardStore";
import { appErrorText } from "./Step1Project";
import css from "../wizard.module.css";

type Candidate = ResultOf<"agents.detect">["candidates"][number];
type Spec = ResultOf<"agents.get">["agents"][number];

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

type Probe =
  | { state: "idle" }
  | { state: "running"; name: string; started: number }
  | { state: "ok"; name: string; seconds: number }
  | { state: "fail"; name: string; code: string; text: string };

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
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [agents, setAgents] = useState<Spec[]>([]);
  const [revision, setRevision] = useState<string | null>(null);
  const [choice, setChoice] = useState<string | null>(agent?.id ?? null);
  const [manualName, setManualName] = useState("");
  const [manualLine, setManualLine] = useState("");
  const [preset, setPreset] = useState("curator");
  const [probe, setProbe] = useState<Probe>(agent?.probed === true ? { state: "ok", name: agent.name, seconds: 0 } : { state: "idle" });
  const [error, setError] = useState<string | null>(null);
  const probing = useRef(false);

  useEffect(() => {
    void (async () => {
      try {
        const [detected, got] = await Promise.all([client().call("agents.detect", {}), client().call("agents.get", {})]);
        setCandidates(detected.candidates);
        setAgents(got.agents);
        setRevision(got.revision ?? null);
      } catch (err) {
        setError(toRpcError(err).message);
      }
    })();
  }, []);

  /** 사용자 설정에 더한다 (이미 있으면 그대로) */
  const ensureSaved = async (spec: Spec): Promise<boolean> => {
    if (agents.some((a) => a.id === spec.id)) return true;
    try {
      const next = [...agents, spec];
      const r = await client().call("agents.set", { agents: next, default_agent: spec.id, base_revision: revision });
      setAgents(next);
      setRevision(r.revision);
      void refreshAgents();
      return true;
    } catch (err) {
      setError(toRpcError(err).message);
      return false;
    }
  };

  const runProbe = async (spec: Spec) => {
    // 첫 await 전에 잡는다 (시험 중 다른 줄을 누르면 agents.set이 같은 revision으로 두 번 가고 시험이 겹친다)
    if (probing.current) return;
    probing.current = true;
    try {
      await probeOnce(spec);
    } finally {
      probing.current = false;
    }
  };

  const probeOnce = async (spec: Spec) => {
    setError(null);
    if (!(await ensureSaved(spec))) return;
    const started = Date.now();
    setProbe({ state: "running", name: spec.name, started });
    setAgent({ id: spec.id, name: spec.name, probed: false, kind: "cli" });
    try {
      const r = await window.kookabug.app.agentProbe(spec.id);
      if (r.ok) {
        setProbe({ state: "ok", name: spec.name, seconds: (Date.now() - started) / 1000 });
        setAgent({ id: spec.id, name: spec.name, probed: true, kind: "cli" });
        setStepWarnings(5, []);
      } else {
        const code = String(r.error_code ?? r.code ?? r.state ?? "probe_failed");
        setProbe({ state: "fail", name: spec.name, code, text: PROBE_FAIL[code] ?? "Kookabug 도구 호출을 보지 못했어요" });
      }
    } catch (err) {
      const text = appErrorText(err);
      const code = /^([a-z_]+):/.exec(err instanceof Error ? err.message.replace(/^Error invoking remote method '[^']*': (\w*Error: )?/, "") : "")?.[1] ?? "probe_failed";
      setProbe({ state: "fail", name: spec.name, code, text: PROBE_FAIL[code] ?? text });
    }
  };

  const pickCandidate = (c: Candidate) => {
    setChoice(c.id);
    if (!c.installed) {
      setProbe({ state: "fail", name: c.name, code: "cli_not_found", text: "설치되지 않았어요" });
      return;
    }
    void runProbe({ id: c.id, name: c.name, command: c.command, args: c.args });
  };

  const pickSaved = (a: Spec) => {
    setChoice(a.id);
    void runProbe(a);
  };

  const addManual = () => {
    const argv = splitCommandLine(manualLine);
    if (manualName.trim() === "" || argv.length === 0) return;
    const id = `custom-${manualName.trim().toLowerCase().replace(/[^a-z0-9_.-]+/g, "-").replace(/^-+|-+$/g, "") || "agent"}`.slice(0, 64);
    setChoice(id);
    void runProbe({ id, name: manualName.trim(), command: argv[0], args: argv.slice(1) });
  };

  const pickApiKey = () => {
    setChoice("apikey");
    setProbe({ state: "idle" });
    setAgent({ id: "apikey", name: "API 키만", probed: false, kind: "apikey" });
  };

  const savePreset = async (): Promise<boolean> => {
    try {
      const info = await client().call("permissions.get", {});
      const user = (info.layers ?? []).find((l) => l.layer === "user");
      const current = (user?.permissions ?? {}) as Record<string, unknown>;
      await client().call("permissions.set", {
        layer: "user",
        permissions: { ...current, preset },
        base_revision: user?.revision ?? null,
      });
      void refreshPermissions();
      return true;
    } catch (err) {
      setError(toRpcError(err).message);
      return false;
    }
  };

  const next = async (): Promise<boolean> => {
    if (!(await savePreset())) return false;
    const label = PRESETS.find(([p]) => p === preset)?.[1].replace(" · 추천", "") ?? preset;
    if (choice === "apikey") {
      setStepWarnings(5, ["agent_api_key_only"]);
      setSummary(5, `API 키만 · 판단 노드 전용 (Init 불가)`, true);
    } else {
      setSummary(5, `${agent?.name ?? ""} · ${label} · 시험 통과`);
    }
    return true;
  };

  const savedOnly = agents.filter((a) => !candidates.some((c) => c.id === a.id));
  const ready = probe.state === "ok" || choice === "apikey";

  return (
    <StepShell
      title="어떤 Agent와 일할까요?"
      lead="Agent가 게임 정보를 모으고, 테스트를 만들고, 실패 원인을 찾아요. 나중에 연결해도 돼요."
      primary={{ label: "다음", enabled: ready, run: next }}
      right={
        <>
          <div className={css.caption}>고르면 바로 연결을 시험해요. 통과해야 "다음"이 켜져요.</div>
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
        {candidates.map((c) => (
          <label key={c.id} className={css.row} data-selected={choice === c.id} data-agent={c.id}>
            <span className={css.avatar} aria-hidden="true">
              {initial(c.name)}
            </span>
            <span className={css.rowText}>
              <span className={css.rowTitle}>
                {c.name}
                {c.installed && <span className={css.tag}>감지됨</span>}
                {choice === c.id && probe.state === "ok" && <span className={css.tag}>연결 시험 통과</span>}
              </span>
              <span className={css.rowSub}>{c.installed ? "설치됨" : "설치 안 됨"}</span>
            </span>
            <input type="radio" name="agent" checked={choice === c.id} onChange={() => pickCandidate(c)} />
          </label>
        ))}
        {savedOnly.map((a) => (
          <label key={a.id} className={css.row} data-selected={choice === a.id} data-agent={a.id}>
            <span className={css.avatar} aria-hidden="true">
              {initial(a.name)}
            </span>
            <span className={css.rowText}>
              <span className={css.rowTitle}>
                {a.name}
                {choice === a.id && probe.state === "ok" && <span className={css.tag}>연결 시험 통과</span>}
              </span>
              <span className={css.rowSub}>사용자 설정</span>
            </span>
            <input type="radio" name="agent" checked={choice === a.id} onChange={() => pickSaved(a)} />
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
          <input type="radio" name="agent" checked={choice === "manual"} onChange={() => setChoice("manual")} />
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
          <input type="radio" name="agent" checked={choice === "apikey"} onChange={pickApiKey} />
        </label>
      </div>
      {choice === "manual" && (
        <div className={css.inputRow}>
          <input className={css.input} placeholder="이름" aria-label="Agent 이름" value={manualName} onChange={(e) => setManualName(e.target.value)} />
          <input className={`${css.input} ${css.mono}`} placeholder="명령줄" aria-label="Agent 명령줄" value={manualLine} onChange={(e) => setManualLine(e.target.value)} />
          <button type="button" className={css.small} onClick={addManual}>
            추가·시험
          </button>
        </div>
      )}
      <div className={css.field}>
        <span className={css.fieldLabel}>Agent 권한</span>
        <div className={css.seg} role="group" aria-label="Agent 권한">
          {PRESETS.map(([value, label]) => (
            <button key={value} type="button" aria-pressed={preset === value} onClick={() => setPreset(value)}>
              {label}
            </button>
          ))}
        </div>
        <span className={css.hint}>
          {PRESET_TEXT[preset]}
          <br />
          혼자 도는 작업은 7단계 자동화 정책을 따라요.
        </span>
      </div>
      {error !== null && (
        <p role="alert" className={css.error}>
          {error}
        </p>
      )}
    </StepShell>
  );
}
