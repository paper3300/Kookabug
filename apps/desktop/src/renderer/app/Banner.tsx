// daemon 연결 상태 띠 (M2 계획 2.11 "시안에 없는 화면·상태"): 연결 중·끊김·판 다름·오류
import type { DaemonState } from "../../preload/bridge";
import { dismissOpenError, restartDaemon, retryDaemon, useWorkspace } from "../store/workspace";
import css from "./shell.module.css";

interface BannerView {
  tone: "info" | "warn" | "error";
  text: string;
  detail?: string[];
  action?: { label: string; run: () => void };
}

export function bannerOf(state: DaemonState): BannerView | null {
  switch (state.status) {
    case "connecting":
      return { tone: "info", text: "daemon에 연결하는 중…", detail: state.logPath ? [`로그: ${state.logPath}`] : undefined };
    case "disconnected": {
      const seconds = state.retryInMs === undefined ? null : (state.retryInMs / 1000).toLocaleString("ko-KR");
      return {
        tone: "warn",
        text: `daemon 연결이 끊겼어요.${seconds === null ? "" : ` ${seconds}초 뒤 다시 연결해요`} (${state.attempt ?? 1}번째)`,
        detail: state.message ? [state.message] : undefined,
        action: { label: "지금 다시 연결", run: () => void retryDaemon() },
      };
    }
    case "mismatch":
      return {
        tone: "error",
        text: state.runActive
          ? `daemon 판(${state.protocol ?? "?"})이 앱(${state.appProtocol})과 달라요. 진행 중인 실행이 끝나면 다시 시작할 수 있어요`
          : `daemon 판(${state.protocol ?? "?"})이 앱(${state.appProtocol})과 달라요`,
        action: { label: "daemon 다시 시작", run: () => void restartDaemon() },
      };
    case "error":
      if (state.error === "cli_not_found") {
        return {
          tone: "error",
          text: "kookabug CLI를 찾지 못했어요. 찾아본 경로:",
          detail: state.tried,
          action: { label: "다시 시도", run: () => void retryDaemon() },
        };
      }
      return {
        tone: "error",
        text: state.error === "timeout" ? "daemon을 시작하지 못했어요 (15초 안에 준비되지 않음)" : (state.message ?? "daemon 오류"),
        detail: state.logPath ? [`로그: ${state.logPath}`] : undefined,
        action: { label: "다시 시도", run: () => void retryDaemon() },
      };
    default:
      return null;
  }
}

const TONE = { info: css.bannerInfo, warn: css.bannerWarn, error: css.bannerError };

/** 앱 틀에서 폴더 열기가 실패했을 때 (지금 프로젝트는 그대로 둔다). 시작 화면은 Welcome이 보여 준다 */
export function OpenErrorBanner() {
  const error = useWorkspace((s) => s.openError);
  if (error === null) return null;
  return (
    <div role="alert" aria-label="폴더 열기 오류" className={`${css.banner} ${css.bannerError}`}>
      <span className={css.bannerText}>
        {openErrorText(error.reason)}
        <span className={css.bannerDetail}>{error.path}</span>
      </span>
      <button type="button" className={css.bannerButton} onClick={dismissOpenError}>
        닫기
      </button>
    </div>
  );
}

export function openErrorText(reason: "not_workspace" | "not_found"): string {
  return reason === "not_workspace" ? "Kookabug 프로젝트가 아닙니다" : "폴더를 찾을 수 없습니다";
}

export function Banner() {
  const state = useWorkspace((s) => s.daemon);
  const view = bannerOf(state);
  if (view === null) return null;
  return (
    <div role="status" aria-label="daemon 연결" data-status={state.status} className={`${css.banner} ${TONE[view.tone]}`}>
      <span className={css.bannerText}>
        {view.text}
        {view.detail?.map((d) => (
          <span key={d} className={css.bannerDetail}>
            {d}
          </span>
        ))}
      </span>
      {view.action && (
        <button type="button" className={css.bannerButton} onClick={view.action.run}>
          {view.action.label}
        </button>
      )}
    </div>
  );
}
