// 3단계 환경 점검 (시안 Setup3Check): 주 프로세스가 `kookabug doctor --json`을 돌린다. 끝나면 "계속"이 켜진다 —
// 경고가 있어도 진행하고 완료 요약에 남긴다 (KB문서 13장). 항목 설명(detail)에는 이 PC 경로가 있어 보이지 않는다
import { useEffect, useState } from "react";
import { Spinner } from "../../app/Spinner";
import { StepShell } from "../Wizard";
import { setReady, setStepWarnings, setSummary } from "../wizardStore";
import { appErrorText } from "./Step1Project";
import css from "../wizard.module.css";

/** doctor 항목 ID → 사람이 읽는 이름 (모르는 ID는 그대로) */
export const CHECK_LABEL: Record<string, string> = {
  python: "Python 실행 환경",
  "import.numpy": "수치 계산 (numpy)",
  "import.cv2": "이미지 찾기 (OpenCV)",
  "import.onnxruntime": "글자 읽기 엔진",
  "import.windows_capture": "화면 캡처 (WGC)",
  "dll.origin": "실행 라이브러리",
  "ocr.models": "글자 읽기 (OCR) 모델",
  dpi: "화면 배율 (DPI)",
  "smoke.fake": "실행기 자체 시험",
  "video.encoder": "영상 기록",
  "desktop.input_desktop": "입력 전달",
  "desktop.capture": "창 캡처",
  "desktop.static_reuse": "정지 화면 재사용",
  "desktop.foreground": "창 앞으로 가져오기",
};

type Checks = { id: string; ok: boolean }[];

export function Step3Check() {
  const [checks, setChecks] = useState<Checks | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [round, setRound] = useState(0);

  useEffect(() => {
    let alive = true;
    setChecks(null);
    setError(null);
    setReady(3, false);
    void window.kookabug.app
      .doctor()
      .then((r) => {
        if (!alive) return;
        setChecks(r.checks);
        const failed = r.checks.filter((c) => !c.ok);
        setStepWarnings(3, failed.map((c) => `check_failed:${c.id}`));
        const passed = r.checks.length - failed.length;
        setSummary(3, failed.length === 0 ? `통과 ${passed}` : `통과 ${passed} · 경고 ${failed.length}`, failed.length > 0);
        setReady(3, true);
      })
      .catch((err: unknown) => {
        if (!alive) return;
        setError(appErrorText(err));
        setStepWarnings(3, ["check_not_run"]);
        setSummary(3, "점검하지 못함", true);
        // 점검을 못 돌려도 막지 않는다 (경고로 남기고 진행)
        setReady(3, true);
      });
    return () => {
      alive = false;
    };
  }, [round]);

  const failed = checks?.filter((c) => !c.ok) ?? [];
  const ready = checks !== null || error !== null;
  return (
    <StepShell
      title="제대로 보고 누를 수 있는지 확인할게요"
      lead="화면 캡처, 글자 읽기, 입력을 한 번씩 시험해요. 경고가 있어도 계속할 수 있어요."
      primary={{ label: "계속", enabled: ready }}
      right={
        <div className={css.card} data-part="check-result">
          <div className={css.cardHead}>
            점검 결과
            <small>{checks === null ? (error !== null ? "점검 못 함" : "점검 중…") : `통과 ${checks.length - failed.length} · 경고 ${failed.length}`}</small>
          </div>
          {failed.length === 0 && checks !== null && <div className={css.band}>모두 통과했어요.</div>}
          {failed.length > 0 && (
            <div className={css.band} data-tone="fail">
              경고는 완료 화면 요약에 남아요. 고친 뒤 "다시 점검"할 수 있어요.
            </div>
          )}
        </div>
      }
    >
      <div className={css.list} data-part="check-list">
        {checks === null && error === null && (
          <div className={css.row}>
            <Spinner label="점검하는 중… (몇 초 걸려요)" delay={0} />
          </div>
        )}
        {error !== null && <div className={css.row}>점검을 돌리지 못했어요: {error}</div>}
        {checks?.map((c) => (
          <div key={c.id} className={css.row} data-check={c.id} data-ok={c.ok}>
            <span className={css.mark} data-state={c.ok ? "ok" : "warn"}>
              {c.ok ? "✓" : "!"}
            </span>
            <span className={css.rowText}>
              <span className={css.rowTitle} style={{ fontWeight: 400 }}>
                {CHECK_LABEL[c.id] ?? c.id}
              </span>
            </span>
          </div>
        ))}
      </div>
      <button type="button" className={css.small} style={{ alignSelf: "flex-start" }} disabled={!ready} onClick={() => setRound((r) => r + 1)}>
        다시 점검
      </button>
    </StepShell>
  );
}
