// 단계마다 저장 위치 배지 (KB문서 13장: 팀 · 이 PC · 사용자 · Windows 자격 증명) — 팀원에게 공유되는 설정인지 보이게
import type { Storage } from "./wizardStore";
import css from "./wizard.module.css";

export const STORAGE_LABEL: Record<Storage, string> = {
  team: "팀 공유",
  pc: "이 PC",
  user: "사용자",
  credential: "Windows 자격 증명",
};

export function StorageBadge({ storage }: { storage: Storage }) {
  return (
    <span className={css.badge} data-storage={storage} data-part="storage-badge">
      {STORAGE_LABEL[storage]}
    </span>
  );
}
