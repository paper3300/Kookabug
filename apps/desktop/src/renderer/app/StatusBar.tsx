// 상태 바 (M2 계획 2.8 "상태 바"): 대기 중이면 무채색, 실행 중이면 파랑(T11). T7은 연결 상태와
// 실행 환경(캡처·OCR·Python·플러그인 수)을 보여 준다
import { useWorkspace } from "../store/workspace";
import { DotIcon } from "../theme/icons";
import css from "./shell.module.css";

const CONNECTION = {
  idle: ["연결 없음", css.statusWarn],
  connecting: ["연결 중…", css.statusWarn],
  connected: ["daemon 연결됨", css.statusOk],
  disconnected: ["연결 끊김", css.statusWarn],
  mismatch: ["판 다름", css.statusError],
  error: ["daemon 오류", css.statusError],
} as const;

function pythonVersion(v: string): string {
  return v.split(".").slice(0, 2).join(".");
}

export function StatusBar() {
  const daemon = useWorkspace((s) => s.daemon);
  const info = useWorkspace((s) => s.info);
  const [label, tone] = CONNECTION[daemon.status];
  const runtime = info?.runtime;
  const capture = runtime ? `캡처 ${runtime.capture ? runtime.capture.toUpperCase() : "없음"}` : null;
  const ocr = runtime ? `OCR ${runtime.ocr ? "사용 가능" : "없음"}` : null;
  return (
    <footer aria-label="상태 바" className={css.statusbar} data-part="statusbar">
      <span className={css.statusItem} data-status={daemon.status} title={daemon.message}>
        <DotIcon className={tone} />
        {label}
      </span>
      <div className={css.spacer} />
      {runtime && (
        <>
          <span className={css.statusItem} title={runtime.ocr ?? undefined}>
            {capture} · {ocr}
          </span>
          <span className={css.statusItem}>Python {pythonVersion(runtime.python)}</span>
          <span className={css.statusItem}>플러그인 {info?.plugins.length ?? 0}</span>
        </>
      )}
    </footer>
  );
}
