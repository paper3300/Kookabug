// 녹화 사이드바 (시안 Recorder 왼쪽, M4 계획 2.11, T9·T10). 녹화 전(시안 없음, U1): 창 고르기·게임 띄워서 녹화.
// 녹화 중: 빨간 점 "REC 02:14", 일시정지·화면 확인 삽입·값 확인 삽입·녹화 정지. 비밀값 띠(주황), 녹화된 스텝 목록,
// 변환 옵션, 아래 "커서 위치에 노드로 삽입"·"새 테스트로 저장". 시안에 없는 상태 문구는 labels.ts (검수 M10)
import { useEffect, useMemo, useState } from "react";
import { useNow } from "../run/view";
import { ask } from "../store/dialog";
import { openTab, openRecTab, useTabs } from "../store/tabs";
import { useWorkspace } from "../store/workspace";
import { ChevronDownIcon, ChevronRightIcon } from "../theme/icons";
import { commitInsert, commitNewTest, insertTarget, STUCK_TEXT } from "./commit";
import {
  commitBlocker,
  LIVE_STATES,
  REVIEW_TEXT,
  secretUnresolved,
  sidebarStateText,
  stepLabel,
  stepMarks,
  stopReasonText,
  warningText,
  type RecorderStep,
} from "./labels";
import {
  beginCheck,
  createSecret,
  discardRecording,
  dismissNotice,
  elapsedNow,
  loadRedactSetting,
  loadSecrets,
  loadWindows,
  pauseRecording,
  resumeRecording,
  selectStep,
  setOption,
  startRecording,
  stopRecording,
  updateStep,
  useRecorder,
} from "./recorderStore";
import css from "./recorder.module.css";

const NO_STEPS: readonly string[] = [];

function Section({ title, open, onToggle }: { title: string; open: boolean; onToggle(): void }) {
  return (
    <button type="button" aria-expanded={open} className={css.section} onClick={onToggle}>
      {open ? <ChevronDownIcon /> : <ChevronRightIcon />}
      <span>{title}</span>
    </button>
  );
}

/** 녹화 전 (시안 없음, U1): 창 목록에서 고르기 또는 게임 띄워서 녹화 */
function StartPanel() {
  const windows = useRecorder((s) => s.windows);
  const busy = useRecorder((s) => s.busy);
  const connected = useWorkspace((s) => s.daemon.status === "connected");
  const [picked, setPicked] = useState<number | null>(null);
  useEffect(() => {
    if (connected) void loadWindows();
  }, [connected]);
  const list = windows ?? [];
  const handle = picked !== null && list.some((w) => w.handle === picked) ? picked : null;
  return (
    <div className={css.start} data-part="rec-start">
      <span className={css.hint}>게임 창을 골라 녹화하거나, 워크스페이스 게임 설정으로 띄워서 녹화해요.</span>
      <label className={css.field}>
        녹화할 창
        <select
          aria-label="녹화할 창"
          className={css.select}
          value={handle ?? ""}
          onChange={(e) => setPicked(e.target.value === "" ? null : Number(e.target.value))}
        >
          <option value="">{windows === null ? "창 목록 읽는 중…" : list.length === 0 ? "보이는 창이 없어요" : "창을 고르세요"}</option>
          {list.map((w) => (
            <option key={w.handle} value={w.handle}>
              {w.title} · {w.process} {w.client_size[0]}×{w.client_size[1]}
            </option>
          ))}
        </select>
      </label>
      <div className={css.buttons}>
        <button type="button" className={css.button} disabled={!connected} onClick={() => void loadWindows()}>
          창 목록 새로고침
        </button>
        <button
          type="button"
          className={css.primary}
          disabled={!connected || handle === null || busy !== null}
          onClick={() => handle !== null && void startRecording({ window: handle })}
        >
          녹화 시작
        </button>
        <button type="button" className={css.button} disabled={!connected || busy !== null} onClick={() => void startRecording({ launch: true })}>
          게임 띄워서 녹화
        </button>
      </div>
    </div>
  );
}

function Controls() {
  const state = useRecorder((s) => s.state);
  const busy = useRecorder((s) => s.busy);
  const checkMode = useRecorder((s) => s.checkMode);
  if (state === null || !state.owned) return null;
  const live = LIVE_STATES.has(state.state);
  const canCheck = state.state === "recording" || state.state === "paused" || state.state === "stopped";
  const check = (kind: "visible" | "text") => {
    beginCheck(checkMode === kind ? null : kind);
    openRecTab(state.window?.title ?? null);
  };
  return (
    <div className={css.controls} data-part="rec-controls">
      {state.state === "paused" ? (
        <button type="button" className={css.button} disabled={busy !== null} onClick={() => void resumeRecording()}>
          계속
        </button>
      ) : (
        live && (
          <button type="button" className={css.button} disabled={busy !== null || state.state !== "recording"} onClick={() => void pauseRecording()}>
            일시정지
          </button>
        )
      )}
      <button type="button" className={css.button} aria-pressed={checkMode === "visible"} disabled={!canCheck} onClick={() => check("visible")}>
        화면 확인 삽입
      </button>
      <button type="button" className={css.button} aria-pressed={checkMode === "text"} disabled={!canCheck} onClick={() => check("text")}>
        값 확인 삽입
      </button>
      {live ? (
        <button type="button" className={css.stop} disabled={busy !== null || state.state === "starting"} onClick={() => void stopRecording()}>
          녹화 정지
        </button>
      ) : (
        (state.state === "stopped" || state.state === "committing") && (
          <button
            type="button"
            className={css.button}
            disabled={busy !== null}
            onClick={async () => {
              const r = await ask({
                title: "이 녹화를 버릴까요?",
                message: "녹화한 스텝과 임시 화면이 지워져요. 이미 저장한 찾기 대상 파일은 남아요.",
                buttons: [
                  { label: "버리기", value: "discard", primary: true },
                  { label: "취소", value: "cancel" },
                ],
                cancelValue: "cancel",
              });
              if (r.value === "discard") void discardRecording();
            }}
          >
            녹화 버리기
          </button>
        )
      )}
    </div>
  );
}

/** 비밀값 띠 (시안 주황 띠): 키 없는 비밀값 스텝 · 비밀번호인지 모르는 스텝 · 판정 중 */
function SecretBanner({ steps, marks }: { steps: RecorderStep[]; marks: Map<string, { mark: string }> }) {
  const secrets = useRecorder((s) => s.secrets);
  const envNote = useRecorder((s) => s.envNote);
  const rows = steps.filter((s) => s.kind === "text" && (secretUnresolved(s) || s.text_state === "needs_review" || s.text_state === "pending"));
  if (rows.length === 0) return null;
  return (
    <div className={css.secretBanner} role="region" aria-label="비밀값" data-part="secret-banner">
      {rows.map((s) => {
        const mark = marks.get(s.step)?.mark ?? "";
        if (s.text_state === "pending") {
          return (
            <span key={s.step} data-part="secret-pending" data-step={s.step}>
              스텝 {mark}의 입력이 비밀번호인지 판정 중이에요…
            </span>
          );
        }
        if (s.text_state === "needs_review") return <ReviewRow key={s.step} step={s} mark={mark} />;
        return <SecretRow key={s.step} step={s} mark={mark} secrets={secrets.map((k) => k.key)} envNote={envNote} />;
      })}
    </div>
  );
}

function SecretRow({ step, mark, secrets, envNote }: { step: RecorderStep; mark: string; secrets: string[]; envNote: string | null }) {
  const [key, setKey] = useState("");
  const listId = `rec-secrets-${step.step}`;
  const choose = () => {
    const k = key.trim();
    if (k !== "") void updateStep(step.step, { secret_key: k });
  };
  const create = async () => {
    const r = await ask({
      title: "이 값으로 새 비밀값 만들기",
      message: "녹화한 비밀번호를 자격 증명 관리자에 저장하고 그 키를 골라요. 값은 파일에 쓰지 않아요.",
      input: { label: "키 이름", value: key.trim(), placeholder: "예: accounts.qa_tester_01" },
      buttons: [
        { label: "만들기", value: "create", primary: true },
        { label: "취소", value: "cancel" },
      ],
      cancelValue: "cancel",
      check: (t) => (/^[A-Za-z0-9_.-]+$/.test(t.trim()) ? null : "영문·숫자·_ . - 만 쓸 수 있어요"),
    });
    if (r.value === "create") void createSecret(step.step, r.text.trim());
  };
  return (
    <div className={css.secretRow} data-part="secret-row" data-step={step.step}>
      <span>스텝 {mark}에서 비밀번호 칸에 입력했어요. 글자 그대로 저장하지 않으니 쓸 비밀값을 고르세요.</span>
      <label className={css.secretField}>
        비밀값
        <input
          aria-label="비밀값 키"
          className={css.select}
          list={listId}
          value={key}
          placeholder={secrets.length > 0 ? `${secrets[0]} (자격 증명 관리자)` : "키 이름"}
          onChange={(e) => setKey(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") choose();
          }}
        />
        <datalist id={listId}>
          {secrets.map((k) => (
            <option key={k} value={k}>
              {k} (자격 증명 관리자)
            </option>
          ))}
        </datalist>
        <button type="button" className={css.button} disabled={key.trim() === ""} onClick={choose}>
          고르기
        </button>
      </label>
      <span className={css.secretActions}>
        <button type="button" className={css.link} onClick={() => void create()}>
          이 값으로 새 비밀값 만들기…
        </button>
        {envNote !== null && envNote !== "" && <span className={css.hint}>{envNote}</span>}
      </span>
    </div>
  );
}

/** 비밀값·확인 필요 → 일반 글자: 원문을 처음 보이는 순간이라 한 번 확인한다 (U3, confirm_reveal) */
async function revealAsOrdinary(step: RecorderStep): Promise<void> {
  const r = await ask({
    title: "글자를 보이고 일반 글자로 저장할까요?",
    message: "이 입력은 비밀번호가 아니라고 확인하면 친 글자가 그대로 보이고 그래프에 저장돼요.",
    buttons: [
      { label: "일반 글자로", value: "ok", primary: true },
      { label: "취소", value: "cancel" },
    ],
    cancelValue: "cancel",
  });
  if (r.value === "ok") void updateStep(step.step, { text_state: "ordinary", confirm_reveal: true });
}

/** 고른 글자 스텝의 판정 바꾸기 (2.8 사람 표시 — 사이드바 목록 전환, B5 검수 M5) */
function TextToggle({ step }: { step: RecorderStep }) {
  if (step.text_state === "ordinary") {
    return (
      <button type="button" className={css.link} data-part="rec-mark-secret" onClick={(e) => (e.stopPropagation(), void updateStep(step.step, { text_state: "secret" }))}>
        비밀값으로
      </button>
    );
  }
  if (step.text_state === "secret") {
    return (
      <button type="button" className={css.link} data-part="rec-mark-ordinary" onClick={(e) => (e.stopPropagation(), void revealAsOrdinary(step))}>
        일반 글자로 (글자 보이기)
      </button>
    );
  }
  return null;
}

function ReviewRow({ step, mark }: { step: RecorderStep; mark: string }) {
  const reveal = () => revealAsOrdinary(step);
  return (
    <div className={css.secretRow} data-part="review-row" data-step={step.step}>
      <span>
        스텝 {mark} 입력이 비밀번호인지 확인하지 못했어요
        {step.needs_review.length > 0 ? ` (${step.needs_review.map((r) => REVIEW_TEXT[r] ?? r).join(", ")})` : ""}.
      </span>
      <span className={css.secretActions}>
        <button type="button" className={css.button} onClick={() => void updateStep(step.step, { text_state: "secret" })}>
          비밀값으로
        </button>
        <button type="button" className={css.button} onClick={() => void reveal()}>
          일반 글자로 (글자 보이기)
        </button>
      </span>
    </div>
  );
}

function StepList({ steps, marks }: { steps: RecorderStep[]; marks: Map<string, { mark: string; dot: "step" | "special" | "wait" }> }) {
  const selected = useRecorder((s) => s.selected);
  // 선택자는 같은 참조를 돌려야 한다 (새 빈 배열이면 무한 렌더)
  const flagged = useRecorder((s) => s.notice?.steps ?? NO_STEPS);
  const redact = useRecorder((s) => s.redactSecrets);
  const windowTitle = useRecorder((s) => s.state?.window?.title ?? null);
  const remove = async (step: RecorderStep, mark: string) => {
    const r = await ask({
      title: `스텝 ${mark || "(대기)"}을(를) 지울까요?`,
      buttons: [
        { label: "지우기", value: "delete", primary: true },
        { label: "취소", value: "cancel" },
      ],
      cancelValue: "cancel",
    });
    if (r.value === "delete") void updateStep(step.step, { delete: true });
  };
  return (
    <ol className={css.steps} aria-label="녹화된 스텝" data-part="rec-steps">
      {steps.map((s) => {
        const label = stepLabel(s, marks, redact);
        const isSel = s.step === selected;
        return (
          <li
            key={s.step}
            className={`${css.step} ${isSel ? css.stepSelected : ""} ${flagged.includes(s.step) ? css.stepFlagged : ""}`}
            data-part="rec-step"
            data-step={s.step}
            data-kind={s.kind}
            data-text-state={s.text_state ?? ""}
            data-flagged={flagged.includes(s.step)}
            aria-selected={isSel}
            tabIndex={0}
            onClick={() => {
              selectStep(s.step);
              openRecTab(windowTitle);
            }}
            onKeyDown={(e) => {
              if (e.key === "Delete") void remove(s, label.mark);
            }}
            onContextMenu={(e) => {
              e.preventDefault();
              void remove(s, label.mark);
            }}
          >
            <span className={`${css.dot} ${label.dot === "special" ? css.dotSpecial : label.dot === "wait" ? css.dotWait : ""}`} data-part="rec-mark">
              {label.mark}
            </span>
            <span className={css.stepText}>
              <span className={css.stepTitle}>{label.title}</span>
              <span className={css.stepRaw} data-part="rec-raw">
                {label.raw}
              </span>
              {label.note !== "" && (
                <span className={label.tone === "review" ? css.noteReview : label.tone === "secret" ? css.noteSecret : css.note} data-part="rec-note" data-tone={label.tone}>
                  {label.note}
                </span>
              )}
              {isSel && s.kind === "text" && (
                <span className={css.rowActions}>
                  <TextToggle step={s} />
                </span>
              )}
              {isSel && s.needs_review.length > 0 && s.kind !== "text" && (
                <span className={css.rowActions}>
                  <button type="button" className={css.link} onClick={(e) => (e.stopPropagation(), void updateStep(s.step, { keep: true }))}>
                    그대로 남기기
                  </button>
                  <button type="button" className={css.link} onClick={(e) => (e.stopPropagation(), void remove(s, label.mark))}>
                    지우기
                  </button>
                </span>
              )}
            </span>
          </li>
        );
      })}
      {steps.length === 0 && <li className={css.empty}>게임에서 클릭·입력하면 여기에 스텝이 쌓여요</li>}
    </ol>
  );
}

function Options() {
  const options = useRecorder((s) => s.options);
  return (
    <div className={css.options} data-part="rec-options">
      <label className={css.check}>
        <input type="checkbox" checked={options.wait_as_appear} onChange={(e) => setOption("wait_as_appear", e.target.checked)} />
        기다린 시간을 "나타날 때까지 대기"로 바꾸기
      </label>
      <label className={css.check}>
        <input type="checkbox" checked={options.crop_targets} onChange={(e) => setOption("crop_targets", e.target.checked)} />
        클릭 직전 화면에서 클릭 지점 주변을 잘라 찾기 대상 만들기
      </label>
      <label className={`${css.check} ${css.checkFixed}`}>
        <input type="checkbox" checked disabled />
        Kookabug가 보낸 입력은 녹화하지 않기 (항상)
      </label>
    </div>
  );
}

function SaveButtons({ steps }: { steps: RecorderStep[] }) {
  const busy = useRecorder((s) => s.busy);
  const state = useRecorder((s) => s.state);
  const stuck = useRecorder((s) => s.retryBlocked);
  // 탭이 바뀌면 삽입 가능 여부가 바뀐다
  useTabs((s) => s.active);
  const blocker = stuck ? STUCK_TEXT : (commitBlocker(steps) ?? (state?.state === "starting" ? "녹화 준비 중이에요" : null));
  const target = insertTarget();
  const insertBlock = blocker ?? (target === null ? "넣을 그래프 탭을 열고 노드를 고르세요" : null);
  return (
    <div className={css.save} data-part="rec-save">
      <button
        type="button"
        className={css.primary}
        disabled={insertBlock !== null || busy !== null}
        title={insertBlock ?? "고른 노드 뒤에 녹화한 노드를 넣어요"}
        onClick={() => void commitInsert()}
      >
        커서 위치에 노드로 삽입
      </button>
      <button
        type="button"
        className={css.button}
        disabled={blocker !== null || busy !== null}
        title={blocker ?? "녹화를 새 테스트 파일로 저장해요"}
        onClick={() => void commitNewTest()}
      >
        새 테스트로 저장
      </button>
    </div>
  );
}

function Committed() {
  const committed = useRecorder((s) => s.committed);
  if (committed === null) return null;
  return (
    <div className={css.committed} role="status" data-part="rec-committed">
      <span>
        <button type="button" className={css.link} onClick={() => openTab({ path: committed.graph, kind: "graph", graphKind: "test" })}>
          {committed.graph}
        </button>
        에 저장했어요 · F5로 바로 재생
      </span>
      {committed.warnings.map((w) => (
        <span key={w} className={css.noteReview}>
          {w}
        </span>
      ))}
    </div>
  );
}

export function RecorderSidebar() {
  const state = useRecorder((s) => s.state);
  const stateAt = useRecorder((s) => s.stateAt);
  const steps = useRecorder((s) => s.steps);
  const notice = useRecorder((s) => s.notice);
  const connected = useWorkspace((s) => s.daemon.status === "connected");
  const [stepsOpen, setStepsOpen] = useState(true);
  const [optionsOpen, setOptionsOpen] = useState(true);
  const recording = state?.state === "recording";
  const now = useNow(recording, 500);
  const marks = useMemo(() => stepMarks(steps), [steps]);
  useEffect(() => {
    if (!connected) return;
    void loadSecrets();
    void loadRedactSetting();
  }, [connected]);
  const owned = state !== null && state.owned;
  const session = owned && ["starting", "recording", "paused", "stopped", "committing"].includes(state.state);
  const elsewhere = state !== null && !state.owned && ["starting", "recording", "paused", "stopped", "committing"].includes(state.state);
  const headline = state === null ? null : sidebarStateText(state, elapsedNow({ state, stateAt }, now));
  const reason = owned ? stopReasonText(state.stop_reason) : null;
  const warnings = owned && LIVE_STATES.has(state.state) ? (state.warnings ?? []) : [];
  const notForeground = owned && state.state === "recording" && state.foreground === false;
  return (
    <div className={css.sidebar} data-part="recorder-sidebar" data-state={state?.state ?? ""} data-owned={String(owned)}>
      <div className={css.header} data-part="sidebar-header">
        <span>녹화</span>
        {headline !== null && (
          <span className={LIVE_STATES.has(state?.state ?? "") && owned ? css.rec : css.headState} data-part="rec-state">
            {owned && LIVE_STATES.has(state.state) && <span className={css.recDot} aria-hidden="true" />}
            {headline}
          </span>
        )}
      </div>
      <div className={css.scroll}>
        {reason !== null && (
          <div role="alert" className={css.errorBand} data-part="rec-stop-reason" data-reason={state?.stop_reason ?? ""}>
            {reason}
          </div>
        )}
        {notice !== null && (
          <div role="alert" className={notice.tone === "error" ? css.errorBand : css.infoBand} data-part="rec-notice">
            <span>{notice.text}</span>
            <button type="button" className={css.link} onClick={dismissNotice}>
              닫기
            </button>
          </div>
        )}
        {elsewhere && (
          <div className={css.infoBand} data-part="rec-elsewhere">
            다른 창에서 녹화 중이에요. 그 창에서 정지하거나 저장하면 여기서 새로 녹화할 수 있어요.
          </div>
        )}
        {!session && !elsewhere && <StartPanel />}
        {session && <Controls />}
        {notForeground && (
          <div className={css.warnBand} data-part="rec-warning" data-code="not_foreground">
            게임 창이 앞에 없어요 — 입력을 녹화하지 않는 중
          </div>
        )}
        {warnings
          .filter((w) => w.code !== "not_foreground")
          .map((w) => (
            <div key={w.code} className={css.warnBand} data-part="rec-warning" data-code={w.code}>
              {warningText(w)}
            </div>
          ))}
        {session && <SecretBanner steps={steps} marks={marks} />}
        {session && (
          <>
            <Section title={`녹화된 스텝 · ${steps.filter((s) => s.kind !== "wait" && s.kind !== "delay").length}`} open={stepsOpen} onToggle={() => setStepsOpen(!stepsOpen)} />
            {stepsOpen && <StepList steps={steps} marks={marks} />}
          </>
        )}
        <Committed />
        <Section title="변환 옵션" open={optionsOpen} onToggle={() => setOptionsOpen(!optionsOpen)} />
        {optionsOpen && <Options />}
      </div>
      {session && <SaveButtons steps={steps} />}
    </div>
  );
}
