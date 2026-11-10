// 환경설정 "설정 도우미" 탭 (`settings:wizard`, M8 계획 3.17): 단계마다 완료·건너뜀·경고. 그 단계만 다시 연다
import { useEffect, useState } from "react";
import { client, toRpcError } from "../rpc/client";
import { openSetupStep } from "./ShortWizardWatch";
import { StorageBadge } from "./StorageBadge";
import { STEPS, useWizard, type StepNo, type WizardFile } from "./wizardStore";
import css from "./wizard.module.css";

export function SetupHelper() {
  const [file, setFile] = useState<WizardFile | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const open = useWizard((s) => s.open);

  useEffect(() => {
    if (open) return;
    // 마법사를 닫을 때마다 다시 읽는다 (그 사이 단계가 끝났을 수 있다)
    void client()
      .call("wizard.get", {})
      .then((r) => setFile(r.wizard as WizardFile | null))
      .catch((err: unknown) => setError(toRpcError(err).message));
  }, [open]);

  return (
    <div style={{ padding: "20px 28px", overflow: "auto", height: "100%", boxSizing: "border-box" }} data-part="setup-helper">
      <h2 className={css.title} style={{ fontSize: 20, marginTop: 0 }}>
        설정 도우미
      </h2>
      <p className={css.lead}>건너뛴 단계와 경고가 여기 남아요. 단계 하나만 다시 열 수 있어요.</p>
      {error !== null && <p className={css.error}>{error}</p>}
      <div className={css.list} style={{ marginTop: 14, maxWidth: 720 }}>
        {STEPS.filter((s) => s.n >= 1 && s.n <= 8).map((s) => {
          const done = file?.done.includes(s.n) === true;
          const skipped = file?.skipped.includes(s.n) === true;
          const warns = file?.warnings.filter((w) => w.step === s.n) ?? [];
          return (
            <div key={s.n} className={css.row} data-step={s.n} data-done={done} data-skipped={skipped}>
              <span className={css.avatar}>{s.n}</span>
              <span className={css.rowText}>
                <span className={css.rowTitle}>
                  {s.title}
                  {done && <span className={css.tag}>완료</span>}
                  {skipped && (
                    <span className={css.tag} data-tone="muted">
                      건너뜀
                    </span>
                  )}
                  {warns.length > 0 && (
                    <span className={css.tag} data-tone="warn">
                      경고 {warns.length}
                    </span>
                  )}
                </span>
                <span className={css.rowSub}>{warns.map((w) => w.code).join(" · ") || (s.required ? "필수" : "선택")}</span>
              </span>
              {s.storage.map((st) => (
                <StorageBadge key={st} storage={st} />
              ))}
              {s.n !== 1 && (
                <button type="button" className={css.small} onClick={() => void openSetupStep(s.n as StepNo)}>
                  다시 열기
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
