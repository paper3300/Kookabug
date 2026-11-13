// 보고함 테스트 계정 질문 → 4단계 등록 (UX5). 키마다 값을 주 프로세스로 넘겨 자격 증명 관리자에 쓰고, 다 되면 그 질문을
// 답함으로 남긴다. 답 글은 고정 글 — daemon이 키 등록을 확인하고 키 이름만 담은 글로 바꿔 남긴다 (값은 어디에도 없다)
import type { CredentialAsk } from "./wizardStore";

/** 칸 값이 등록할 수 있는 꼴인가 (주 프로세스·CLI가 다시 본다) */
export function secretInputOk(key: string, value: string): boolean {
  // eslint-disable-next-line no-control-regex
  return /^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)*$/.test(key) && key.length <= 128 && value.length > 0 && value.length <= 1024 && !/[\u0000-\u001f]/.test(value);
}

/** 질문의 키를 다 채웠나 (이미 저장된 키는 비워 두면 그대로) */
export function askReady(ask: CredentialAsk, values: Readonly<Record<string, string>>, saved: readonly string[]): boolean {
  return ask.keys.every((k) => {
    const v = values[k] ?? "";
    return secretInputOk(k, v) || (v === "" && saved.includes(k));
  });
}

export const ANSWER_TEXT = "테스트 계정 등록";

/** 등록 → 답함. 하나라도 실패하면 답하지 않고 던진다 */
export async function registerAsk(
  ask: CredentialAsk,
  values: Readonly<Record<string, string>>,
  saved: readonly string[],
  deps: { register(key: string, value: string): Promise<unknown>; answer(id: string, rev: number, text: string): Promise<unknown> },
): Promise<void> {
  for (const key of ask.keys) {
    const value = values[key] ?? "";
    if (value === "" && saved.includes(key)) continue;
    await deps.register(key, value);
  }
  await deps.answer(ask.unknown, ask.rev, ANSWER_TEXT);
}
