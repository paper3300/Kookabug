// 새 찾기 대상 (M2 계획 2.9 "열기"): 이름을 묻고 targets/<이름>.target.json TARGET 탭을 연다. 파일은 저장할 때
// 생긴다 (target.save base_revision null). 속성 편집기의 "새 대상 만들기"면 저장 뒤 그 핀에 $target을 넣는다
import { ask } from "../store/dialog";
import { openTab } from "../store/tabs";
import { useWorkspace } from "../store/workspace";
import { createTargetDoc, getTarget, type TargetOrigin } from "./targetStore";

const BAD_SEGMENT = /[\\:*?"<>|\u0000-\u001f]/;

/** 새 target 이름 검사 ("/"로 하위 폴더). 괜찮으면 null */
export function checkTargetName(name: string): string | null {
  const n = name.trim();
  if (n === "") return "이름을 적어 주세요";
  if (n.length > 120) return "이름이 너무 길어요";
  const parts = n.split("/");
  for (const p of parts) {
    if (p === "" || p.startsWith(".") || p.endsWith(".") || p.endsWith(" ") || BAD_SEGMENT.test(p)) {
      return "파일 이름에 쓸 수 없는 글자가 있어요";
    }
  }
  const path = newTargetPath(n);
  if (useWorkspace.getState().entries.some((e) => e.path === path) || getTarget(path) !== undefined) {
    return `'${path}'이(가) 이미 있어요`;
  }
  return null;
}

export function newTargetPath(name: string): string {
  return `targets/${name.trim()}.target.json`;
}

/** 이름을 묻고 새 TARGET 탭을 연다. 만든 경로 (취소면 null) */
export async function newTargetInteractive(origin: TargetOrigin | null = null, suggestion = ""): Promise<string | null> {
  const r = await ask({
    title: "새 찾기 대상",
    message: "정지 화면에서 영역을 골라 저장하면 PNG와 *.target.json이 생겨요.",
    input: { label: "이름", value: suggestion, placeholder: "예: lobby/start_button" },
    buttons: [
      { label: "만들기", value: "create", primary: true },
      { label: "취소", value: "cancel" },
    ],
    cancelValue: "cancel",
    check: checkTargetName,
  });
  if (r.value !== "create") return null;
  const path = newTargetPath(r.text);
  createTargetDoc(path, origin);
  openTab({ path, kind: "target" });
  return path;
}
