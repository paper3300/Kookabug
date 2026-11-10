// 화면을 채운 뒤 다른 곳에서 설정이 바뀌었을 때 (B7 검수 H5). 단계는 화면을 채울 때 읽은 sha·revision으로 저장하고,
// daemon이 revision_conflict로 거부하면 이 안내를 보인다. 최신 sha를 몰래 갈아 끼워 다시 저장하지 않는다 — 사람이 다시 읽어
// 바뀐 값을 보고 확인한다
import { toRpcError } from "../rpc/client";
import css from "./wizard.module.css";

export const CONFLICT_TEXT = "다른 곳에서 설정이 바뀌었어요";

export function isConflict(err: unknown): boolean {
  return toRpcError(err).kind === "revision_conflict";
}

export function ConflictNotice({ onReload }: { onReload: () => void }) {
  return (
    <p role="alert" className={css.error} data-part="wizard-conflict">
      {CONFLICT_TEXT} —{" "}
      <button type="button" className={css.linkButton} onClick={onReload}>
        다시 읽기
      </button>
    </p>
  );
}
