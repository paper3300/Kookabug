// 6단계 원본 칸 (순수 판정, B7): 입력 글 → 원본 정의, 화면 초기값, 저장 계획

export interface SourceSlot {
  id: string;
  kind: string;
  title: string;
  icon: string;
}

export const SLOTS: readonly SourceSlot[] = [
  { id: "game_code", kind: "code", title: "게임 코드", icon: "{ }" },
  { id: "data_table", kind: "data", title: "데이터 테이블", icon: "▦" },
  { id: "string_table", kind: "strings", title: "문자열 테이블", icon: "가" },
  { id: "design_doc", kind: "design_doc", title: "기획 문서", icon: "¶" },
  { id: "patch_notes", kind: "patch_notes", title: "패치 노트", icon: "✎" },
  { id: "qa_sheet", kind: "qa_sheet", title: "QA 시트", icon: "≡" },
];

export type SourceDef = { id: string; kind: string; title: string; path?: string; url?: string; local?: boolean };

/** 입력 글 → 원본 정의. URL은 팀, 상대 경로는 팀, 절대 경로는 이 PC(local.json에 경로) */
export function toSource(slot: SourceSlot, value: string): { def: SourceDef; localPath: string | null } | null {
  const v = value.trim();
  if (v === "") return null;
  if (/^https?:\/\//i.test(v)) return { def: { id: slot.id, kind: slot.kind, title: slot.title, url: v }, localPath: null };
  if (/^[A-Za-z]:[\\/]|^\\\\/.test(v)) {
    return { def: { id: slot.id, kind: slot.kind, title: slot.title, local: true }, localPath: v };
  }
  return { def: { id: slot.id, kind: slot.kind, title: slot.title, path: v.replace(/\\/g, "/") }, localPath: null };
}

/** 칸 ID 가운데 팀 원본에 같은 ID가 둘 이상인 것. 그 칸은 저장하지 않는다 (어느 항목을 고칠지 모른다, B7-2 검수 H3) */
export function duplicateIds(sources: readonly SourceDef[]): Set<string> {
  const seen = new Set<string>();
  const dup = new Set<string>();
  for (const s of sources) {
    if (!SLOTS.some((slot) => slot.id === s.id)) continue;
    if (seen.has(s.id)) dup.add(s.id);
    seen.add(s.id);
  }
  return dup;
}

export const DUPLICATE_TEXT = "같은 ID의 원본이 여러 개예요 — kookabug.json에서 정리해 주세요";

/** 칸 초기값: 팀 원본의 URL·경로, `local: true`면 이 PC 경로(local.json) */
export function initialValues(
  sources: readonly SourceDef[],
  localSources: Readonly<Record<string, string | undefined>>,
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const s of sources) {
    if (!SLOTS.some((slot) => slot.id === s.id)) continue;
    out[s.id] = s.local === true ? (localSources[s.id] ?? "") : (s.url ?? s.path ?? "");
  }
  return out;
}

/**
 * 저장할 것: 사람이 바꾼 칸만 바꾼다 (B7 검수 H4). 바꾸지 않은 칸 — 이 PC 경로를 못 읽어 빈 칸인 local 원본 포함 — 과 칸 밖의
 * 원본은 그대로 두고, 사람이 비운 칸만 지운다. local은 바꾼 칸의 이 PC 경로(아니면 null = 지움).
 * 같은 ID 원본이 여럿인 칸은 바뀌어도 쓰지 않고 `blocked`로 돌려준다 — 그 항목들은 그대로 (B7-2 검수 H3)
 */
export function planSources(
  sources: readonly SourceDef[],
  initial: Readonly<Record<string, string>>,
  values: Readonly<Record<string, string>>,
): { defs: SourceDef[]; local: Record<string, string | null>; changed: boolean; blocked: string[] } {
  const dup = duplicateIds(sources);
  const edited = SLOTS.filter((slot) => (values[slot.id] ?? "").trim() !== (initial[slot.id] ?? "").trim());
  const blocked = edited.filter((slot) => dup.has(slot.id)).map((slot) => slot.id);
  const changedSlots = edited.filter((slot) => !dup.has(slot.id));
  const parsed = new Map(changedSlots.map((slot) => [slot.id, toSource(slot, values[slot.id] ?? "")]));
  const defs: SourceDef[] = [];
  for (const s of sources) {
    const next = parsed.get(s.id);
    if (next === undefined) defs.push(s);
    else if (next !== null) defs.push(next.def);
  }
  for (const slot of changedSlots) {
    const next = parsed.get(slot.id);
    if (next != null && !sources.some((s) => s.id === slot.id)) defs.push(next.def);
  }
  const local: Record<string, string | null> = {};
  for (const slot of changedSlots) local[slot.id] = parsed.get(slot.id)?.localPath ?? null;
  return { defs, local, changed: changedSlots.length > 0, blocked };
}
