// REC 탭의 오른쪽 속성 탭 (UX6): 녹화 사이드바·REC 탭에서 고른 스텝의 정보와 동작. 녹화 사이드바 행 안에 펼치던
// 비밀값/일반 전환·남기기·지우기, 값 확인 스텝의 기댓값, 고른 영역의 속성(매칭 미리보기·클릭 지점·검색 범위·글자·배율)
import { useMemo } from "react";
import { TargetAreaPanels } from "../target/TargetEditor";
import { stepLabel, stepMarks } from "./labels";
import { recAdapter, useRecDoc } from "./recAdapter";
import { removeStep, TextToggle } from "./RecorderSidebar";
import { ExpectedText, recEditable } from "./RecTab";
import { updateStep, useRecorder } from "./recorderStore";
import css from "./recorder.module.css";

export function RecProps() {
  const steps = useRecorder((s) => s.steps);
  const selected = useRecorder((s) => s.selected);
  const checkMode = useRecorder((s) => s.checkMode);
  const redact = useRecorder((s) => s.redactSecrets);
  const doc = useRecDoc((s) => s.doc);
  const marks = useMemo(() => stepMarks(steps), [steps]);
  const step = steps.find((s) => s.step === selected) ?? null;
  if (checkMode !== null) {
    return (
      <div className={css.propsEmpty} data-part="rec-props-empty">
        {checkMode === "visible" ? "화면 확인" : "값 확인"}으로 넣을 영역을 정지 화면에서 드래그한 뒤 "넣기"를 누르세요
      </div>
    );
  }
  if (step === null) {
    return (
      <div className={css.propsEmpty} data-part="rec-props-empty">
        녹화된 스텝을 고르면 정보와 동작이 보여요
      </div>
    );
  }
  const label = stepLabel(step, marks, redact);
  const review = step.needs_review.length > 0 && step.kind !== "text";
  return (
    <div className={css.props} data-part="rec-props" data-step={step.step} data-kind={step.kind}>
      <div className={css.propsHead} data-part="rec-props-head">
        <span className={css.dot}>{label.mark}</span>
        <span className={css.stepText}>
          <span className={css.stepTitle}>{label.title}</span>
          <span className={css.stepRaw}>{label.raw}</span>
          {label.note !== "" && (
            <span className={label.tone === "review" ? css.noteReview : label.tone === "secret" ? css.noteSecret : css.note}>{label.note}</span>
          )}
        </span>
      </div>
      {(step.kind === "text" || review) && (
        <div className={css.rowActions} data-part="rec-props-actions">
          {step.kind === "text" && <TextToggle step={step} />}
          {review && (
            <>
              <button type="button" className={css.link} data-part="rec-keep" onClick={() => void updateStep(step.step, { keep: true })}>
                그대로 남기기
              </button>
              <button type="button" className={css.link} data-part="rec-delete" onClick={() => void removeStep(step, label.mark)}>
                지우기
              </button>
            </>
          )}
        </div>
      )}
      {step.kind === "check_text" && <ExpectedText key={step.step} step={step} />}
      {recEditable(step, checkMode, doc.step) && <TargetAreaPanels doc={doc} adapter={recAdapter} />}
    </div>
  );
}
