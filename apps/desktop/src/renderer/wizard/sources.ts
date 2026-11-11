// 6단계 원본 칸 (순수 판정, B7·UX1 U4): 입력 글 → 원본 정의, 화면 초기값, 저장 계획.
// 칸 하나에 줄이 여러 개일 수 있다. 첫 줄 ID는 칸 ID 그대로(`design_doc`), 더한 줄은 `<칸>_<무작위 6자 hex>`
// (`design_doc_3fa91c`, 예전 `design_doc_2`도 그대로 읽는다). 지운 줄의 ID가 다시 쓰이지 않고 남은 줄의 ID도 그대로라
// 이 PC 경로(local.json sources.<id>)가 다른 줄에 붙지 않는다

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

/** 원본 ID가 칸의 몇 번째 줄 ID인가: 칸 ID 그대로면 1, 예전 `<칸>_<n>`(n ≥ 2)이면 n, 아니면 null */
export function rowNumber(slot: SourceSlot, id: string): number | null {
  if (id === slot.id) return 1;
  const m = /^(.+)_([1-9][0-9]*)$/.exec(id);
  if (m === null || m[1] !== slot.id) return null;
  const n = Number(m[2]);
  return n >= 2 ? n : null;
}

/** 새 줄 ID `<칸>_<무작위 6자 hex>`의 hex (아니면 null) */
export function rowTag(slot: SourceSlot, id: string): string | null {
  const m = /^(.+)_([0-9a-f]{6})$/.exec(id);
  return m !== null && m[1] === slot.id && rowNumber(slot, id) === null ? m[2] : null;
}

/** 칸 안 줄 순서: 첫 줄 1, 예전 번호 줄은 그 번호, 무작위 줄은 뒤(같은 값 — 원래 순서 유지). 칸 줄이 아니면 null */
export function rowOrder(slot: SourceSlot, id: string): number | null {
  return rowNumber(slot, id) ?? (rowTag(slot, id) !== null ? Number.MAX_SAFE_INTEGER : null);
}

/** 원본 ID의 칸 (칸 밖 ID면 null) */
export function slotOf(id: string): SourceSlot | null {
  return SLOTS.find((slot) => rowOrder(slot, id) !== null) ?? null;
}

/** 줄 ID의 원본 이름 (첫 줄은 칸 이름, 예전 번호 줄은 "기획 문서 2", 무작위 줄은 "기획 문서 3fa91c") */
export function rowTitle(slot: SourceSlot, id: string): string {
  const n = rowNumber(slot, id);
  if (n !== null) return n === 1 ? slot.title : `${slot.title} ${n}`;
  const tag = rowTag(slot, id);
  return tag === null ? slot.title : `${slot.title} ${tag}`;
}

/** 입력 글 → 원본 정의. URL은 팀, 상대 경로는 팀, 절대 경로는 이 PC(local.json에 경로). `id`가 없으면 칸 ID */
export function toSource(slot: SourceSlot, value: string, id: string = slot.id): { def: SourceDef; localPath: string | null } | null {
  const v = value.trim();
  if (v === "") return null;
  const head = { id, kind: slot.kind, title: rowTitle(slot, id) };
  if (/^https?:\/\//i.test(v)) return { def: { ...head, url: v }, localPath: null };
  if (/^[A-Za-z]:[\\/]|^\\\\/.test(v)) {
    return { def: { ...head, local: true }, localPath: v };
  }
  return { def: { ...head, path: v.replace(/\\/g, "/") }, localPath: null };
}

/** 칸 줄 ID 가운데 팀 원본에 같은 ID가 둘 이상인 것. 그 줄은 저장하지 않는다 (어느 항목을 고칠지 모른다, B7-2 검수 H3) */
export function duplicateIds(sources: readonly SourceDef[]): Set<string> {
  const seen = new Set<string>();
  const dup = new Set<string>();
  for (const s of sources) {
    if (slotOf(s.id) === null) continue;
    if (seen.has(s.id)) dup.add(s.id);
    seen.add(s.id);
  }
  return dup;
}

export const DUPLICATE_TEXT = "같은 ID의 원본이 여러 개예요 — kookabug.json에서 정리해 주세요";

/** 줄 초기값 (줄 ID → 글): 팀 원본의 URL·경로, `local: true`면 이 PC 경로(local.json) */
export function initialValues(
  sources: readonly SourceDef[],
  localSources: Readonly<Record<string, string | undefined>>,
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const s of sources) {
    if (slotOf(s.id) === null) continue;
    out[s.id] = s.local === true ? (localSources[s.id] ?? "") : (s.url ?? s.path ?? "");
  }
  return out;
}

/** 칸마다 줄 ID (팀 원본 순서, 줄 번호가 작은 것부터). 원본이 없는 칸은 첫 줄 하나 */
export function initialRows(sources: readonly SourceDef[]): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const slot of SLOTS) {
    const ids = [...new Set(sources.map((s) => s.id).filter((id) => rowOrder(slot, id) !== null))];
    ids.sort((a, b) => (rowOrder(slot, a) ?? 0) - (rowOrder(slot, b) ?? 0));
    out[slot.id] = ids.length > 0 ? ids : [slot.id];
  }
  return out;
}

function randomTag(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(3));
  return [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/**
 * "+ 추가"가 매길 다음 줄 ID: `<칸>_<무작위 6자 hex>` (예: `design_doc_3fa91c`). 번호가 아니라 지운 줄 이력 없이도 다시 쓰이지
 * 않는다 (UX1 검수 M1). 지금 있는 ID(`taken`)와 같으면 다시 뽑는다
 */
export function nextRowId(slot: SourceSlot, taken: Iterable<string>, random: () => string = randomTag): string {
  const seen = new Set(taken);
  for (;;) {
    const id = `${slot.id}_${random()}`;
    if (!seen.has(id) && rowTag(slot, id) !== null) return id;
  }
}

/**
 * 저장할 것: 사람이 바꾼 줄만 바꾼다 (B7 검수 H4). 바꾸지 않은 줄 — 이 PC 경로를 못 읽어 빈 줄인 local 원본 포함 — 과 칸 밖의
 * 원본은 그대로 두고, 사람이 비우거나 지운 줄(`values`에 빈 글이거나 없음)만 지운다. local은 바꾼 줄의 이 PC 경로(아니면 null = 지움).
 * 같은 ID 원본이 여럿인 줄은 바뀌어도 쓰지 않고 `blocked`로 돌려준다 — 그 항목들은 그대로 (B7-2 검수 H3)
 */
export function planSources(
  sources: readonly SourceDef[],
  initial: Readonly<Record<string, string>>,
  values: Readonly<Record<string, string>>,
): { defs: SourceDef[]; local: Record<string, string | null>; changed: boolean; blocked: string[] } {
  const dup = duplicateIds(sources);
  const ids = [...new Set([...Object.keys(initial), ...Object.keys(values)])].filter((id) => slotOf(id) !== null);
  const edited = ids.filter((id) => (values[id] ?? "").trim() !== (initial[id] ?? "").trim());
  const blocked = edited.filter((id) => dup.has(id));
  const changed = edited.filter((id) => !dup.has(id));
  const parsed = new Map(changed.map((id) => [id, toSource(slotOf(id)!, values[id] ?? "", id)]));
  const defs: SourceDef[] = [];
  for (const s of sources) {
    const next = parsed.get(s.id);
    if (next === undefined) defs.push(s);
    else if (next !== null) defs.push(next.def);
  }
  // 새 줄은 칸 순서·줄 순서(무작위 줄은 더한 순서)로 뒤에 붙인다
  const added = changed
    .filter((id) => parsed.get(id) != null && !sources.some((s) => s.id === id))
    .sort((a, b) => {
      const sa = SLOTS.indexOf(slotOf(a)!);
      const sb = SLOTS.indexOf(slotOf(b)!);
      return sa !== sb ? sa - sb : (rowOrder(slotOf(a)!, a) ?? 0) - (rowOrder(slotOf(b)!, b) ?? 0);
    });
  for (const id of added) defs.push(parsed.get(id)!.def);
  const local: Record<string, string | null> = {};
  for (const id of changed) local[id] = parsed.get(id)?.localPath ?? null;
  return { defs, local, changed: changed.length > 0, blocked };
}
