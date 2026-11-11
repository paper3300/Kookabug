// 9단계 완료 (시안 Wizard9Init·Wizard9NoAgent): 설정 요약·경고·건너뛴 단계, 처음 할 일. Agent 연결 시험을 통과했으면
// "Agent로 Init 시작"(주 프로세스 → `agent-job run --playbook init`, 결과는 보고함)이 기본, 아니면 Init을 끄고
// "Agent를 연결하면 쓸 수 있어요 · 지금 연결"(5단계만 열기), 녹화를 기본으로 고른다
import { useState } from "react";
import { showSide } from "../../app/Sidebar";
import { openReportsTab } from "../../reports/reportsStore";
import { useWorkspace } from "../../store/workspace";
import { StepShell } from "../Wizard";
import { finishWizard, reopenStep, stepInfo, useWizard, type StepNo } from "../wizardStore";
import { appErrorText } from "./Step1Project";
import css from "../wizard.module.css";

type First = "init" | "record" | "empty";

const ROWS: [StepNo, string][] = [
  [1, "프로젝트"],
  [2, "게임"],
  [3, "환경 점검"],
  [4, "테스트 계정"],
  [5, "Agent"],
  [6, "정보 원본"],
  [7, "자동화"],
  [8, "기록"],
];

export function Step9Done() {
  const progress = useWizard((s) => s.progress);
  const summary = useWizard((s) => s.summary);
  const agent = useWizard((s) => s.agent);
  const name = useWorkspace((s) => s.name);
  const initReady = agent !== null && agent.probed && agent.kind !== "apikey";
  const [first, setFirst] = useState<First>(initReady ? "init" : "record");
  const [error, setError] = useState<string | null>(null);
  const rows = progress.mode === "new" ? ROWS : ROWS.filter(([n]) => progress.steps.includes(n));

  const start = async (): Promise<boolean> => {
    setError(null);
    if (first === "init") {
      if (!initReady || agent === null) return false;
      try {
        const r = await window.kookabug.app.agentJobRun("init", agent.id);
        if (!r.started) {
          setError(r.error_code === "job_active" ? "다른 작업이 도는 중이에요. 보고함에서 확인해 주세요" : "Init을 시작하지 못했어요");
          return false;
        }
      } catch (err) {
        setError(appErrorText(err));
        return false;
      }
      await finishWizard();
      openReportsTab();
      return false;
    }
    await finishWizard();
    if (first === "record") showSide("recorder");
    return false;
  };

  const rowText = (n: StepNo): { text: string; warn: boolean; skipped: boolean } => {
    if (progress.skipped.includes(n)) return { text: "건너뜀", warn: false, skipped: true };
    const s = summary[n];
    if (n === 1 && s === undefined && name !== null) return { text: name, warn: false, skipped: false };
    if (s !== undefined) return { text: s.text, warn: s.warn === true, skipped: false };
    return { text: progress.done.includes(n) ? "완료" : "—", warn: false, skipped: false };
  };

  const warnings = progress.warnings.length;
  return (
    <StepShell
      title="준비됐어요"
      lead={
        initReady
          ? "Agent가 게임 정보를 모으는 것부터 시작할게요. 설정은 언제든 바꿀 수 있어요."
          : "Agent 없이 시작해요. 게임을 직접 해 보며 첫 테스트를 만들어 볼까요?"
      }
      primary={{
        label: first === "init" ? "Init 시작" : "Kookabug 열기",
        enabled: first !== "init" || initReady,
        run: start,
        busyLabel: first === "init" ? "Init 시작 중…" : "여는 중…",
      }}
      note={warnings > 0 ? `경고 ${warnings}개는 설정 도우미에 남아요` : undefined}
      right={
        initReady ? (
          <>
            <div className={css.caption}>Init 중에도 앱을 쓸 수 있어요. 끝나면 보고함에 결과가 남아요.</div>
            <div className={css.card}>
              <div className={css.cardHead}>
                <span>
                  <span className={css.tag} data-tone="muted">
                    Init
                  </span>{" "}
                  하는 일
                </span>
                <small>최대 예산 안에서</small>
              </div>
              {["설정 확인", "원본 읽기", "게임 켜고 화면 모으기", "기능 지도 · 주장 후보", "미지수 정리 · 보고"].map((t) => (
                <div key={t} className={css.cardRow}>
                  <span className={css.mark} data-state="wait">
                    ○
                  </span>
                  {t}
                </div>
              ))}
            </div>
            <div className={css.card}>
              <div className={css.cardHead}>
                <span className={`${css.tag}`} data-tone="warn">
                  사람만 답할 수 있음
                </span>
                <small>답하지 않아도 계속 진행</small>
              </div>
              <div className={css.cardRow}>원본에서 못 찾은 것은 보고함에 질문으로 올라와요.</div>
            </div>
          </>
        ) : (
          <>
            <div className={css.caption}>Agent는 언제든 연결할 수 있어요</div>
            <div className={css.card}>
              <div className={css.cardHead}>나중에 Agent를 연결하면</div>
              <div className={css.cardRow}>
                <span className={css.mark}>✓</span>
                <span>
                  설정 도우미 열기<small>5단계만 다시 열려요</small>
                </span>
              </div>
              <div className={css.cardRow}>
                <span className={css.mark}>✓</span>연결 시험 통과
              </div>
              <div className={css.cardRow}>
                <span className={css.mark}>✓</span>보고함에서 Init을 시작할 수 있어요
              </div>
            </div>
            <div className={css.card}>
              <div className={css.cardHead}>Agent 없이도 되는 것</div>
              <div className={css.cardRow}>녹화로 테스트 만들기 · 실행과 기록 보기 · 화면 지도 · 비교</div>
            </div>
          </>
        )
      }
    >
      <dl className={css.summary} data-part="wizard-summary">
        {rows.map(([n, label]) => {
          const r = rowText(n);
          return (
            <div key={n} style={{ display: "contents" }}>
              <dt>{label}</dt>
              <dd data-warn={r.warn} data-step={n} data-skipped={r.skipped}>
                {r.text}
                {r.skipped && (
                  <>
                    {" · "}
                    <button type="button" className={css.linkButton} onClick={() => void reopenStep(n)}>
                      {stepInfo(n).title} 다시 열기
                    </button>
                  </>
                )}
              </dd>
            </div>
          );
        })}
      </dl>
      <span className={css.fieldLabel}>처음 할 일</span>
      <div className={css.list} role="radiogroup" aria-label="처음 할 일" data-part="first-task">
        <label className={css.row} data-selected={first === "init"} data-disabled={!initReady} data-first="init">
          <span className={css.rowText}>
            <span className={css.rowTitle}>
              Agent로 Init 시작
              {initReady ? (
                <span className={css.tag} data-tone="muted">
                  추천
                </span>
              ) : (
                <span className={css.tag} data-tone="muted">
                  Agent 필요
                </span>
              )}
            </span>
            <span className={css.rowSub}>
              {initReady ? (
                "게임을 켜고 원본을 읽어 위키를 만들어요"
              ) : agent?.kind === "apikey" ? (
                "Init은 Agent CLI가 필요해요"
              ) : (
                <>
                  Agent를 연결하면 쓸 수 있어요 ·{" "}
                  <button type="button" className={css.linkButton} data-part="connect-now" onClick={() => void reopenStep(5)}>
                    지금 연결
                  </button>
                </>
              )}
            </span>
          </span>
          <input type="radio" name="first" disabled={!initReady} checked={first === "init"} onChange={() => setFirst("init")} />
        </label>
        <label className={css.row} data-selected={first === "record"} data-first="record">
          <span className={css.rowText}>
            <span className={css.rowTitle}>녹화로 첫 테스트 만들기</span>
            <span className={css.rowSub}>게임을 직접 해 보면 노드로 바뀌어요</span>
          </span>
          <input type="radio" name="first" checked={first === "record"} onChange={() => setFirst("record")} />
        </label>
        <label className={css.row} data-selected={first === "empty"} data-first="empty">
          <span className={css.rowText}>
            <span className={css.rowTitle}>빈 에디터로 시작</span>
            <span className={css.rowSub}>노드를 직접 배치해요</span>
          </span>
          <input type="radio" name="first" checked={first === "empty"} onChange={() => setFirst("empty")} />
        </label>
      </div>
      {error !== null && (
        <p role="alert" className={css.error}>
          {error}
        </p>
      )}
    </StepShell>
  );
}
