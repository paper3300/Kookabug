// 승격 대화 상자의 순수 부분 (M7 B5): 확인·승격 params(둘이 같은 값이어야 revision이 맞는다), 결과 글
import type { PromoteTarget } from "./mapStore";

export interface PromoteForm {
  id: string;
  title: string;
  description: string;
  folder: string;
  replaceShot: boolean;
  replaceDetect: boolean;
}

export function promoteParams(target: PromoteTarget, form: PromoteForm) {
  const common = { session: target.session, key: target.key, mode: target.mode };
  if (target.mode === "merge") {
    return {
      ...common,
      ...(target.of !== null ? { id: target.of } : {}),
      replace_shot: form.replaceShot,
      replace_detect: form.replaceDetect,
    };
  }
  return {
    ...common,
    ...(form.id.trim() !== "" ? { id: form.id.trim() } : {}),
    ...(form.folder.trim() !== "" ? { folder: form.folder.trim() } : {}),
  };
}

/** 승격 결과 알림 글 */
export function promotedText(cleanupPending: boolean): string {
  return cleanupPending ? "옮겼어요 — 정리는 다음에 마저 해요" : "옮겼어요";
}

export interface SameCandidate {
  session: string;
  key: string;
  title?: string | null;
}

/** 다른 탐색 세션의 같은 화면일 수 있는 후보 안내 (UX12 1b — 안내만, 합치기는 지도에서) */
export function sameHint(same: readonly SameCandidate[]): string {
  const names = same.map((s) => `${s.title ?? s.key} (세션 ${s.session})`).join(", ");
  return `다른 탐색 세션에 같은 화면일 수 있는 후보: ${names} — 지도에서 합치기로 합칠 수 있어요`;
}
