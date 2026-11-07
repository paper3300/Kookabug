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
