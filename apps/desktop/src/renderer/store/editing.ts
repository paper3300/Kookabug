// 편집 흐름의 사용자 확인 (M2 계획 T9): 저장 안 된 탭 닫기·프로젝트 떠나기·앱 창 닫기 확인.
// 새 그래프 만들기는 newGraph.ts
import { displayName } from "../explorer/tree";
import { dirtyTargets, getTarget, saveTarget, targetDirty } from "../target/targetStore";
import { ask, lockEdits } from "./dialog";
import { dirtyDocs, getDoc, saveDoc, type SaveOutcome } from "./documents";
import { closeTab } from "./tabs";

const saved = (outcome: SaveOutcome) => outcome === "saved" || outcome === "unchanged";

/** TARGET 탭 닫기: 저장 안 된 영역·설정이 있으면 묻는다. 저장이 실패하면(충돌 등) 닫지 않는다 */
async function requestCloseTarget(path: string): Promise<boolean> {
  for (;;) {
    const doc = getTarget(path);
    if (doc === undefined || !targetDirty(doc)) {
      closeTab(path);
      return true;
    }
    const r = await ask({
      title: `'${displayName(path)}'의 변경을 저장할까요?`,
      message: doc.isNew ? "저장하지 않으면 새 대상이 만들어지지 않아요." : "저장하지 않으면 고른 영역과 바꾼 설정이 사라져요.",
      buttons: [
        { label: "저장", value: "save", primary: true },
        { label: "저장 안 함", value: "discard" },
        { label: "취소", value: "cancel" },
      ],
      cancelValue: "cancel",
    });
    if (r.value === "cancel") return false;
    if (r.value === "discard") {
      closeTab(path);
      return true;
    }
    if ((await saveTarget(path)) !== "saved") return false;
  }
}

/**
 * 탭을 닫는다. 저장 안 된 그래프면 저장할지 묻는다. "저장"이면 저장이 끝날 때까지 편집을 잠그고, 끝난 뒤
 * 지금 문서가 여전히 저장 안 된 상태면(저장 실패·충돌) 닫지 않는다 (T9 검수 1차: 저장 대기 중 편집 유실)
 */
export async function requestCloseTab(path: string): Promise<boolean> {
  if (getTarget(path) !== undefined) return requestCloseTarget(path);
  for (;;) {
    const doc = getDoc(path);
    if (doc === undefined || !doc.dirty) {
      closeTab(path);
      return true;
    }
    const r = await ask({
      title: `'${displayName(path)}'의 변경을 저장할까요?`,
      message: "저장하지 않으면 변경이 사라져요.",
      buttons: [
        { label: "저장", value: "save", primary: true },
        { label: "저장 안 함", value: "discard" },
        { label: "취소", value: "cancel" },
      ],
      cancelValue: "cancel",
    });
    if (r.value === "cancel") return false;
    if (r.value === "discard") {
      closeTab(path);
      return true;
    }
    const unlock = lockEdits();
    try {
      if (!saved(await saveDoc(path))) return false;
      // 잠금 덕에 새 편집은 없다. 그래도 저장한 값과 버퍼가 다르면 닫지 않고 다시 묻는다
      if (getDoc(path)?.dirty !== true) {
        closeTab(path);
        return true;
      }
    } finally {
      unlock();
    }
  }
}

/**
 * 저장 안 된 그래프를 묻는다: 프로젝트를 떠나기 전(열기·바꾸기·닫기)과 앱 창을 닫기 전. "모두 저장"이면 저장이
 * 끝날 때까지 편집을 잠그고, 끝난 뒤 남은 저장 안 된 문서가 있으면 다시 묻는다
 */
export async function confirmLeaveDirty(): Promise<boolean> {
  for (;;) {
    const targets = dirtyTargets();
    const dirty = [...dirtyDocs(), ...targets];
    if (dirty.length === 0) return true;
    const r = await ask({
      title: `저장하지 않은 ${targets.length === 0 ? "그래프가" : "파일이"} ${dirty.length}개 있어요`,
      message: dirty.map((d) => d.path).join("\n"),
      buttons: [
        { label: "모두 저장", value: "save", primary: true },
        { label: "저장 안 함", value: "discard" },
        { label: "취소", value: "cancel" },
      ],
      cancelValue: "cancel",
    });
    if (r.value === "cancel") return false;
    if (r.value === "discard") return true;
    const unlock = lockEdits();
    try {
      // target 먼저: 새 target은 저장되면 그것을 만든 그래프 핀을 채운다(그래프가 dirty가 됨). 그 뒤 그래프를
      // 저장해야 참조가 디스크에 남는다 (T12 검수 1차 High 1)
      for (const d of dirtyTargets()) if ((await saveTarget(d.path)) !== "saved") return false;
      for (const d of dirtyDocs()) if (!saved(await saveDoc(d.path))) return false;
    } finally {
      unlock();
    }
  }
}
