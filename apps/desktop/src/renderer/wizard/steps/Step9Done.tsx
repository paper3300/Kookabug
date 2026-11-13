// 9단계 완료 (시안 Wizard9Init·Wizard9NoAgent, UX5 설정·Init 간소화 3절): 설정 요약·경고·건너뛴 단계, 그리고 "Init 시작"이
// 주 단추다 — 처음 할 일은 Agent에게 맡긴다(주 프로세스 → `agent-job run --playbook init`, 결과는 보고함). 녹화는 보조 링크.
// Init에 쓰는 Agent = 5단계 연결 시험(기본 Agent 자동 시험 포함)을 통과한 것만. 없으면 "Kookabug 열기"가 주 단추이고
// "Agent 연결"(5단계만 열기)을 보인다.
// 새 프로젝트 순서에서는 뺀 단계(7 자동화 정책·8 기록)의 기본값을 처음 그릴 때 한 번 저장한다 (없는 블록만)
import { useEffect, useRef, useState } from "react";
import { showSide } from "../../app/Sidebar";
import { openReportsTab } from "../../reports/reportsStore";
import { useWorkspace } from "../../store/workspace";
import { saveSkippedDefaults } from "../defaults";
import { StepShell } from "../Wizard";
import { finishWizard, HELPER_ONLY, initAgent, reopenStep, stepInfo, useWizard, type StepNo } from "../wizardStore";
import { appErrorText } from "./Step1Project";
import css from "../wizard.module.css";

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
  const initId = initAgent(agent);
  const [error, setError] = useState<string | null>(null);
  const [defaults, setDefaults] = useState<"saving" | "saved" | "failed" | null>(null);
  const saving = useRef<Promise<unknown> | null>(null);
  // 이번 순서에 있었던 단계만 (UX5: 새 순서에는 4·7·8이 없다 — 기본값 한 줄로)
  const rows = ROWS.filter(([n]) => progress.steps.includes(n));
  const helperDefaults = progress.mode === "new" && HELPER_ONLY.every((n) => !progress.steps.includes(n));

  useEffect(() => {
    if (!helperDefaults) return;
    setDefaults("saving");
    const run = saveSkippedDefaults()
      .then(() => setDefaults("saved"))
      .catch(() => setDefaults("failed"));
    saving.current = run;
    // 화면을 그릴 때 한 번
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const startInit = async (): Promise<boolean> => {
    setError(null);
    if (initId === null) return false;
    // Init이 정책 블록을 읽기 전에 기본값 저장을 끝낸다
    if (saving.current !== null) await saving.current;
    try {
      const r = await window.kookabug.app.agentJobRun("init", initId);
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
  };

  const openApp = async (record: boolean): Promise<boolean> => {
    if (saving.current !== null) await saving.current;
    await finishWizard();
    if (record) showSide("recorder");
    return false;
  };

  const rowText = (n: StepNo): { text: string; warn: boolean; skipped: boolean } => {
    if (progress.skipped.includes(n)) return { text: n === 6 ? "나중에" : "건너뜀", warn: false, skipped: true };
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
        initId !== null
          ? "Agent가 게임을 켜 보고 기본 정보를 모으는 것부터 시작할게요. 설정은 필요할 때 바꿀 수 있어요."
          : "Agent를 연결하면 게임 정보를 모으는 것부터 맡길 수 있어요."
      }
      primary={
        initId !== null
          ? { label: "Init 시작", enabled: true, run: startInit, busyLabel: "Init 시작 중…" }
          : { label: "Kookabug 열기", enabled: true, run: () => openApp(false), busyLabel: "여는 중…" }
      }
      note={warnings > 0 ? `경고 ${warnings}개는 설정 도우미에 남아요` : undefined}
      right={
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
            {["설정 확인", "원본 훑어보기 · 위키 뼈대 · 기능 목록", "게임 켜고 첫 화면 · 끄기", "게임 실행 · 게임 종료 서브그래프", "보고"].map((t) => (
              <div key={t} className={css.cardRow}>
                <span className={css.mark} data-state="wait">
                  ○
                </span>
                {t}
              </div>
            ))}
          </div>
          <div className={css.card}>
            <div className={css.cardHead}>그다음</div>
            <div className={css.cardRow}>Init 보고에서 "게임 접속 경로 만들기"를 눌러 로비까지 가는 길을 만들어요. 계정은 그때 물어요.</div>
          </div>
        </>
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
        {helperDefaults && (
          <div style={{ display: "contents" }}>
            <dt>자동화 · 기록</dt>
            <dd data-part="wizard-defaults" data-state={defaults ?? ""} data-warn={defaults === "failed"}>
              {defaults === "failed" ? "기본값을 저장하지 못했어요 · 설정 도우미에서 정해 주세요" : "기본값 · 필요할 때 설정 도우미에서 바꿔요"}
            </dd>
          </div>
        )}
      </dl>
      <span className={css.fieldLabel}>처음 할 일</span>
      <div className={css.list} data-part="first-task">
        <div className={css.row} data-first="init" data-disabled={initId === null}>
          <span className={css.rowText}>
            <span className={css.rowTitle}>
              Agent에게 맡기기 · Init
              <span className={css.tag} data-tone="muted">
                {initId !== null ? "추천" : "Agent 필요"}
              </span>
            </span>
            <span className={css.rowSub}>
              {initId !== null ? (
                "게임을 켜 보고 위키 뼈대와 실행·종료 서브그래프를 만들어요"
              ) : agent?.kind === "apikey" ? (
                "Init은 Agent CLI가 필요해요"
              ) : (
                <>
                  Agent를 연결하면 쓸 수 있어요 ·{" "}
                  <button type="button" className={css.linkButton} data-part="connect-now" onClick={() => void reopenStep(5)}>
                    Agent 연결
                  </button>
                </>
              )}
            </span>
          </span>
        </div>
      </div>
      <span className={css.hint}>
        직접 해 보고 싶으면{" "}
        <button type="button" className={css.linkButton} data-part="first-record" onClick={() => void openApp(true)}>
          녹화로 첫 테스트 만들기
        </button>
      </span>
      {error !== null && (
        <p role="alert" className={css.error}>
          {error}
        </p>
      )}
    </StepShell>
  );
}
