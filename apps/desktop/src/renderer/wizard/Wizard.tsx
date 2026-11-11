// 첫 프로젝트 설정 마법사 틀 (M8 계획 3.17, 시안 Wizard5Agent 등). 창 전체를 덮는 겹 화면이라 앱 틀(App·Shell)을
// 고치지 않고 시작 화면(Welcome)과 상태 바(ShortWizardWatch)에서 띄운다 — 둘 중 하나만 그려져 있다
import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Spinner, useDelayed } from "../app/Spinner";
import { WindowControls } from "../app/WindowControls";
import { EnterIcon } from "../theme/icons";
import { StorageBadge } from "./StorageBadge";
import { Step0Start } from "./steps/Step0Start";
import { Step1Project } from "./steps/Step1Project";
import { Step2Game } from "./steps/Step2Game";
import { Step3Check } from "./steps/Step3Check";
import { Step4Accounts } from "./steps/Step4Accounts";
import { Step5Agent } from "./steps/Step5Agent";
import { Step6Sources } from "./steps/Step6Sources";
import { Step7Automation } from "./steps/Step7Automation";
import { Step8Record } from "./steps/Step8Record";
import { Step9Done } from "./steps/Step9Done";
import {
  canAdvance,
  canGoBack,
  canSkip,
  closeWizard,
  goBack,
  goNext,
  goSkip,
  setReady,
  stepInfo,
  useWizard,
} from "./wizardStore";
import css from "./wizard.module.css";

export interface Primary {
  label: string;
  /** 누를 수 있는가 (필수 단계의 완료 조건) */
  enabled: boolean;
  /** 누르면 할 일. true면 완료하고 다음 단계로 (없으면 바로 다음) */
  run?: () => Promise<boolean> | boolean;
  /** 도는 동안 단추 글 (기본 "저장 중…") */
  busyLabel?: string;
}

/** 단계 하나의 틀: 머리(번호·저장 위치)·제목·안내·본문 / 오른쪽 그림 / 아래 이전·진행 점·건너뛰기·다음 */
export function StepShell({
  title,
  lead,
  right,
  primary,
  extra,
  note,
  children,
}: {
  title: string;
  lead: ReactNode;
  right?: ReactNode;
  primary: Primary;
  /** 주 단추 왼쪽의 두 번째 끝내기 단추 (5단계 only 모드의 "저장") */
  extra?: Primary;
  note?: ReactNode;
  children?: ReactNode;
}) {
  const progress = useWizard((s) => s.progress);
  const saveError = useWizard((s) => s.saveError);
  const [busy, setBusy] = useState(false);
  // 진행 중 표시는 ref로 바로 잡는다: 상태(busy)는 다시 그린 뒤에야 보여 같은 틱의 두 번째 클릭·Enter가 지나간다 (B7 반대 검수)
  const inFlight = useRef(false);
  const info = stepInfo(progress.step);
  const optional = canSkip(progress);
  const enabled = primary.enabled && !busy;
  // 진행 표시는 짧은 일(200ms 안)에 깜빡이지 않게 늦게 보인다 (U1)
  const [busyButton, setBusyButton] = useState<"primary" | "extra" | null>(null);
  const showBusy = useDelayed(busy);

  const onPrimary = async (button: Primary = primary) => {
    if (!button.enabled || busy || inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setBusyButton(button === primary ? "primary" : "extra");
    try {
      const go = button.run === undefined ? true : await button.run();
      if (!go) return;
      setReady(progress.step, true);
      await goNext();
    } finally {
      inFlight.current = false;
      setBusy(false);
      setBusyButton(null);
    }
  };

  const label = (button: Primary, which: "primary" | "extra") =>
    showBusy && busyButton === which ? (
      <span className={css.nextBusy}>
        <Spinner size="sm" delay={0} />
        {button.busyLabel ?? "저장 중…"}
      </span>
    ) : (
      button.label
    );

  // ↵ = 다음 (입력 칸 안의 Enter는 그 칸의 몫)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Enter" || e.target !== document.body) return;
      void onPrimary();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  return (
    <div className={css.board}>
      <section className={css.left} data-part="wizard-left">
        <div className={css.head}>
          <span className={css.crumb} data-part="wizard-crumb">
            {progress.step} / 9 · {info.title}
            {progress.step > 0 && progress.step < 9 ? (info.required ? " · 필수" : " · 선택") : ""}
          </span>
          <span className={css.spacer} />
          {info.storage.length > 0 && <span className={css.saveLabel}>저장</span>}
          {info.storage.map((s) => (
            <StorageBadge key={s} storage={s} />
          ))}
        </div>
        <h1 className={css.title}>{title}</h1>
        <p className={css.lead}>{lead}</p>
        <div className={css.body}>{children}</div>
        <div className={css.grow} />
        {note !== undefined && note !== null && <div className={css.note}>{note}</div>}
        {saveError !== null && (
          <p role="alert" className={css.error}>
            진행을 저장하지 못했어요: {saveError}
          </p>
        )}
        <div className={css.footer}>
          <button
            type="button"
            className={css.back}
            disabled={!canGoBack(progress) || busy}
            onClick={() => void goBack()}
          >
            ‹ 이전
          </button>
          <div className={css.dots} aria-hidden="true">
            {progress.mode === "new" &&
              [1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => (
                <span key={n} className={css.dot} data-on={n <= progress.step} data-current={n === progress.step} />
              ))}
          </div>
          <div className={css.actions}>
            {optional && (
              <button type="button" className={css.skip} disabled={busy} onClick={() => void goSkip()}>
                건너뛰기
              </button>
            )}
            {extra !== undefined && (
              <button
                type="button"
                className={css.skip}
                data-part="wizard-extra"
                disabled={!extra.enabled || busy}
                onClick={() => void onPrimary(extra)}
              >
                {label(extra, "extra")}
              </button>
            )}
            <button
              type="button"
              className={css.next}
              data-part="wizard-next"
              disabled={!enabled || !canAdvance(progress, true)}
              onClick={() => void onPrimary()}
            >
              {label(primary, "primary")} <EnterIcon />
            </button>
          </div>
        </div>
      </section>
      <aside className={css.right} data-part="wizard-right">
        {right}
      </aside>
    </div>
  );
}

function CurrentStep({ step }: { step: number }) {
  switch (step) {
    case 0:
      return <Step0Start />;
    case 1:
      return <Step1Project />;
    case 2:
      return <Step2Game />;
    case 3:
      return <Step3Check />;
    case 4:
      return <Step4Accounts />;
    case 5:
      return <Step5Agent />;
    case 6:
      return <Step6Sources />;
    case 7:
      return <Step7Automation />;
    case 8:
      return <Step8Record />;
    default:
      return <Step9Done />;
  }
}

/** 마법사 겹 화면 (열려 있을 때만) */
export function WizardHost() {
  const open = useWizard((s) => s.open);
  const step = useWizard((s) => s.progress.step);
  const mode = useWizard((s) => s.progress.mode);
  if (!open) return null;
  // body에 그린다: 상태 바(쌓임 맥락) 안에서 띄워도 창 전체를 덮게
  return createPortal(
    <div className={css.overlay} data-screen="wizard" data-step={step} data-mode={mode} role="dialog" aria-label="설정 도우미">
      <div className={css.dragBar}>
        <button type="button" className={css.later} data-part="wizard-close" onClick={() => void closeWizard()}>
          나중에 계속
        </button>
        <WindowControls height={32} />
      </div>
      {/* 단계가 바뀌면 단계 컴포넌트를 새로 그린다 (단계 안 상태를 섞지 않는다) */}
      <CurrentStep key={step} step={step} />
    </div>,
    document.body,
  );
}
