// REC 탭 (시안 Recorder 오른쪽 "SampleRPG 캡처", M4 계획 2.10 첫 줄·2.11, T10). 사이드바에서 고른 스텝의 정지 화면을
// target 편집기 부품(TargetEditorBody)으로 고친다 — 편집은 녹화 초안 어댑터(recAdapter)가 recorder.step.update로 보낸다.
// 머리: "정지 화면 · 스텝 3", 안내 줄, 프레임 고르기(클릭 직전·커서 들어오기 전·다음 동작 직전), "찾기 대상 탭으로 열기"
// (초안은 recorder.target.materialize로 그 초안만 지금 파일로), "실시간 화면으로". 화면 확인·값 확인 넣기는 지금 화면에서
// 영역을 고른 뒤 "넣기"(recorder.insert_check) — 그동안 기존 스텝은 편집 대상이 아니다.
// UX6: 탭에는 정지 화면 캔버스만. 고른 스텝의 동작(비밀값/일반 전환·남기기·지우기)·값 확인 기댓값·영역 속성은 오른쪽
// 속성 탭(RecProps.tsx)
import { useEffect, useMemo, useState } from "react";
import { client, toRpcError } from "../rpc/client";
import { FrameView } from "../target/FrameView";
import { TargetEditorBody } from "../target/TargetEditor";
import targetCss from "../target/target.module.css";
import { openTab } from "../store/tabs";
import { LIVE_STATES, recorderErrorText, stepMarks, type RecorderStep } from "./labels";
import { checkRegion, flushDraft, loadRecFrame, readRegion, recAdapter, sendDraft, useRecDoc, type FrameWhich } from "./recAdapter";
import {
  applyExpected,
  beginCheck,
  draftTicket,
  fillExpectedDraft,
  insertCheck,
  refreshSteps,
  selectStep,
  setExpectedDraft,
  useRecorder,
} from "./recorderStore";
import css from "./recorder.module.css";

const WHICH_LABEL: Record<FrameWhich, string> = {
  pre_click: "클릭 직전",
  pre_hover: "커서 들어오기 전",
  pre_next: "다음 동작 직전",
  live: "지금 화면",
};

/** 재사용 target 안내 (B5 검수 M4) */
export const FILE_TARGET_HINT = "기존 찾기 대상이에요 — 고치면 이 화면에서 새 대상으로 바뀌어요 (기존 파일은 그대로)";

function setNotice(text: string): void {
  useRecorder.setState({ notice: { tone: "error", text, steps: [] } });
}

/** "찾기 대상 탭으로 열기": 초안이면 그 초안만 지금 파일로 쓰고(최신 보호 영역 재검사) TARGET 탭으로 */
async function openAsTarget(step: RecorderStep): Promise<void> {
  const target = step.target;
  if (target === undefined) return;
  if (target.source === "file" && target.path !== undefined) {
    openTab({ path: target.path, kind: "target" });
    return;
  }
  if (target.source !== "draft") return;
  if (!(await flushDraft())) return;
  try {
    const written = await client().call("recorder.target.materialize", { step: step.step });
    await refreshSteps();
    openTab({ path: written.path, kind: "target" });
  } catch (err) {
    const e = toRpcError(err);
    setNotice(`찾기 대상 파일로 쓰지 못했어요: ${recorderErrorText(e.kind, e.message)}`);
  }
}

/** 값 확인 스텝의 기댓값 (B5 검수 M6): 고치기 · 글자 읽기로 채우기 → recorder.step.update {equals} */
export function ExpectedText({ step }: { step: RecorderStep }) {
  // 초안은 저장소에 둔다: 속성 탭이 오른쪽 탭 전환·접기로 사라져도 남는다 (UX6 검수 H2)
  const draft = useRecorder((s) => s.expectedDrafts[step.step] ?? null);
  const setDraft = (text: string | null) => setExpectedDraft(step.step, text);
  const [note, setNote] = useState<string | null>(null);
  const value = draft ?? step.equals ?? "";
  const read = async () => {
    const region = readRegion();
    if (region === null) {
      setNote("읽을 영역이 없어요 — 정지 화면에서 영역을 고르세요");
      return;
    }
    const ticket = draftTicket(step.step);
    try {
      const r = await client().call("target.read_text", { frame_id: region.frameId, rect: region.rect });
      // 그 사이 녹화가 바뀌었으면(스텝 ID는 세션마다 다시 쓴다) 쓰지 않는다 (UX6 검수 2 High)
      if (!fillExpectedDraft(ticket, r.text)) return;
      setNote(null);
    } catch (err) {
      const e = toRpcError(err);
      setNote(e.kind === "secret_region_overlap" ? "비밀값 칸과 겹쳐 읽지 않았어요" : `읽지 못했어요: ${e.message}`);
    }
  };
  const apply = () => applyExpected(step.step, value);
  return (
    <div className={css.checkBand} data-part="rec-expected">
      <label className={css.secretField}>
        기댓값
        <input aria-label="기댓값" className={css.select} value={value} onChange={(e) => setDraft(e.target.value)} />
      </label>
      <button type="button" className={css.button} onClick={() => void read()}>
        글자 읽기로 채우기
      </button>
      <button type="button" className={css.primary} disabled={draft === null || draft === (step.equals ?? "")} onClick={() => void apply()}>
        기댓값 적용
      </button>
      {note !== null && <span data-part="rec-expected-note">{note}</span>}
    </div>
  );
}

/** 고른 스텝의 찾기 대상을 고칠 수 있는가 (정지 화면이 그 스텝 것이고 확인 넣기 중이 아님) */
export function recEditable(step: RecorderStep | null, checkMode: string | null, docStep: string | null): boolean {
  return checkMode === null && step !== null && step.target !== undefined && docStep === step.step;
}

export function RecTab() {
  const steps = useRecorder((s) => s.steps);
  const selected = useRecorder((s) => s.selected);
  const checkMode = useRecorder((s) => s.checkMode);
  const state = useRecorder((s) => s.state);
  const doc = useRecDoc((s) => s.doc);
  const step = steps.find((s) => s.step === selected) ?? null;
  const marks = useMemo(() => stepMarks(steps), [steps]);
  const live = state !== null && LIVE_STATES.has(state.state) && state.state !== "starting";
  const stepId = step?.step ?? null;

  // 고른 스텝·확인 모드가 바뀌면 정지 화면을 다시 올린다
  useEffect(() => {
    if (checkMode !== null || stepId === null) {
      if (live) {
        void loadRecFrame(null, "live");
        return;
      }
      // 정지 뒤(실시간 화면 없음)의 확인 넣기: 마지막 스텝의 다음 동작 직전 화면을 빌리기만 한다 (그 스텝은 고치지 않음)
      const last = [...steps].reverse().find((s) => (s.frames ?? []).length > 0);
      if (last !== undefined) {
        const which = (last.frames ?? []).includes("pre_next") ? "pre_next" : (last.frames as FrameWhich[])[0];
        void loadRecFrame(last, which, { bind: false });
      }
      return;
    }
    const s = useRecorder.getState().steps.find((x) => x.step === stepId);
    if (s === undefined) return;
    const which = (s.target?.frame ?? s.frames?.[0] ?? "pre_click") as FrameWhich;
    void loadRecFrame(s, which);
    // 스텝 목록이 갱신될 때마다 다시 올리지 않는다 (고른 스텝·모드가 바뀔 때만)
  }, [stepId, checkMode, live]);

  const frames = (step?.frames ?? []) as FrameWhich[];
  const mark = step === null ? "" : (marks.get(step.step)?.mark ?? "");
  const title =
    checkMode !== null
      ? `${checkMode === "visible" ? "화면 확인" : "값 확인"} 넣기 · ${live ? "지금 화면" : "마지막 스텝 화면"}`
      : step === null
        ? live
          ? "실시간 화면"
          : "정지 화면 · 마지막 스텝"
        : `정지 화면 · 스텝 ${mark || step.node.title}`;
  const draft = step?.target?.source === "draft";
  const fileTarget = checkMode === null && step?.target?.source === "file" && doc.step === step.step && doc.template === null;
  const canOpen = step?.target?.source === "file" || draft;
  const editable = recEditable(step, checkMode, doc.step);
  const region = checkMode !== null ? checkRegion() : null;
  return (
    <div
      className={css.recTab}
      data-part="rec-tab"
      data-step={stepId ?? ""}
      data-doc-step={doc.step ?? ""}
      data-check={checkMode ?? ""}
      data-frame={doc.frame?.frame_id ?? ""}
      data-loading={String(doc.frameLoading)}
      data-sending={String(doc.sending)}
      data-accepted={doc.acceptedTemplate?.join(",") ?? ""}
    >
      <div className={css.recToolbar} data-part="rec-toolbar">
        <span className={css.recTitle} data-part="rec-title">
          {title}
        </span>
        <span className={css.recGuide}>드래그 = 템플릿 영역 · Shift+드래그 = 검색 범위 · 십자선 = 클릭 지점</span>
        <span className={css.spacer} />
        {step !== null && checkMode === null && frames.length > 1 && (
          <select
            aria-label="정지 화면 고르기"
            className={css.select}
            value={doc.which}
            onChange={(e) => {
              const which = e.target.value as FrameWhich;
              void loadRecFrame(step, which).then(() => {
                if (draft) void sendDraft();
              });
            }}
          >
            {frames.map((f) => (
              <option key={f} value={f}>
                {WHICH_LABEL[f]}
              </option>
            ))}
          </select>
        )}
        {step !== null && step.target !== undefined && checkMode === null && (
          <button
            type="button"
            className={css.button}
            disabled={!canOpen}
            title={canOpen ? "이 찾기 대상을 TARGET 탭에서 열어요 (초안이면 지금 파일로 저장)" : "찾기 대상이 없어요 — 영역을 고르세요"}
            onClick={() => void openAsTarget(step)}
          >
            찾기 대상 탭으로 열기
          </button>
        )}
        <button type="button" className={css.button} disabled={!live} title={live ? undefined : "녹화가 끝나 실시간 화면이 없어요"} onClick={() => selectStep(null)}>
          실시간 화면으로
        </button>
      </div>
      {checkMode !== null && (
        <div className={css.checkBand} data-part="rec-check-band">
          <span>{checkMode === "visible" ? "화면 확인으로 넣을 영역을 드래그하세요" : "값 확인으로 넣을 글자 영역을 드래그하세요"}</span>
          <button
            type="button"
            className={css.primary}
            disabled={region === null}
            onClick={() => region !== null && void insertCheck(checkMode, region.frameId, region.rect)}
          >
            넣기
          </button>
          <button type="button" className={css.button} onClick={() => beginCheck(null)}>
            취소
          </button>
        </div>
      )}
      {fileTarget && (
        <div className={css.checkBand} data-part="rec-file-note">
          {FILE_TARGET_HINT}
        </div>
      )}
      {doc.refusal !== null && (
        <div role="alert" className={css.refusal} data-part="rec-refusal">
          {doc.refusal}
        </div>
      )}
      {doc.frameError !== null && (
        <div role="alert" className={css.refusal} data-part="rec-frame-error">
          {doc.frameError}
        </div>
      )}
      <div className={targetCss.editor} data-part="target-editor" data-path="rec:capture" data-status={doc.frame === null ? "loading" : "ready"}>
        {editable ? (
          <TargetEditorBody doc={doc} adapter={recAdapter} />
        ) : (
          <div className={targetCss.body}>
            <FrameView doc={doc} adapter={recAdapter} />
          </div>
        )}
      </div>
    </div>
  );
}
