// 플러그인 화면 모델 (M6 계획 B5·U1): 목록·미리보기·작업 결과를 화면 글로 바꾸는 순수 함수.
// 화면에는 daemon이 인증 정보를 가린 값만 오지만, 로컬 절대 경로(원천 폴더·wheel 파일·file:// git 주소, 오류 문구
// 속 경로)는 여기서 마지막 이름만 남긴다 — 화면·스크린샷에 PC 경로 원문을 내지 않는다
import type { NotificationParamsOf, ParamsOf, ResultOf } from "@kookabug/schema";

export type PluginsList = ResultOf<"plugins.list">;
export type PluginEntry = PluginsList["plugins"][number];
export type PreviewResult = ResultOf<"plugins.preview">;
export type PreviewParams = ParamsOf<"plugins.preview">;
export type EnvStatus = PluginEntry["env_status"];
export type DoneParams = NotificationParamsOf<"plugins.done">;
export type PluginErrorInfo = NonNullable<DoneParams["error"]>;
export type OpKind = DoneParams["kind"];
export type Isolation = NonNullable<PreviewParams["isolation"]>;

/** 권한 6종 (M6 3.1): 화면 이름·뜻 */
export const PERMISSIONS: Readonly<Record<string, { label: string; meaning: string }>> = {
  capture: { label: "화면 캡처", meaning: "게임 창 화면을 읽어요" },
  input: { label: "입력", meaning: "게임 창에 클릭·키를 보내요" },
  process: { label: "프로세스", meaning: "프로그램을 실행하거나 끝내요" },
  filesystem: { label: "파일", meaning: "내 PC의 파일을 읽고 써요" },
  network: { label: "네트워크", meaning: "인터넷·다른 컴퓨터와 통신해요" },
  secrets: { label: "비밀값", meaning: "저장된 비밀값(계정·토큰)을 읽어요" },
};

export function permissionInfo(id: string): { label: string; meaning: string } {
  return PERMISSIONS[id] ?? { label: id, meaning: "알 수 없는 권한이에요" };
}

/** 권한은 표시와 선언 검사뿐이다 (M6 D11·U4) — 신뢰 카드·상세에 같은 문구 */
export const PERMISSION_NOTE = "권한은 노드가 선언한 범위를 알려 줄 뿐, 운영체제 수준에서 막지는 않아요.";

/** 신뢰 카드 첫 문구 (M6 U1) */
export const TRUST_WARNING = "이 플러그인은 내 PC에서 내 권한으로 실행돼요. 출처를 믿을 때만 설치하세요.";

export const ENV_STATUS_TEXT: Readonly<Record<EnvStatus, string>> = {
  ready: "준비됨",
  missing: "준비 필요",
  stale: "조건 다름",
  broken: "환경 깨짐",
};

export const ISOLATION_TEXT: Readonly<Record<Isolation, string>> = {
  auto: "자동 (충돌하면 격리)",
  shared: "공유",
  isolated: "격리",
};

export function envText(env: string): string {
  return env === "shared" ? "공유" : "격리";
}

/** 격리된 까닭 (잠금 isolated_because) */
export function isolationReason(entry: Pick<PluginEntry, "isolated_because" | "conflicts">): string | null {
  if (entry.isolated_because === "declared") return "플러그인이 격리를 요청했어요";
  if (entry.isolated_because === "conflict") {
    const names = entry.conflicts ?? [];
    return names.length > 0 ? `공유 환경과 의존성이 충돌해요 (${names.join(", ")})` : "공유 환경과 의존성이 충돌해요";
  }
  return null;
}

// ── 경로 가리기 ───────────────────────────────────────────────────

// 경로는 공백·한글이 들 수 있어 줄 끝·따옴표·꺾쇠까지 넓게 잡고(보수적), 그 안의 마지막 구분자 뒤 첫 낱말만
// 이름으로 남긴다 — 경로 뒤에 붙은 글이 함께 가려질 수는 있어도 앞 폴더(사용자 이름 등)가 남지는 않는다
const FILE_URI = /file:\/\/[^\r\n"'<>|`]*/gi;
const WIN_PATH = /(?<![\w/\\])(?:[A-Za-z]:[\\/]|\\\\[^\s\\/"'<>|]+[\\/])[^\r\n"'<>|`]*/g;

function lastName(p: string): string {
  const parts = p.replace(/[\\/]+$/, "").split(/[\\/]/).filter((s) => s !== "");
  return parts[parts.length - 1] ?? "";
}

/** 넓게 잡은 경로 조각 → `…<sep>이름` + 경로 뒤 글 (이름은 마지막 구분자 뒤 첫 낱말, 끝 문장 부호는 뒤 글로) */
function shortenSpan(span: string, sep: "\\" | "/"): string {
  const cut = Math.max(span.lastIndexOf("\\"), span.lastIndexOf("/"));
  const tail = span.slice(cut + 1);
  const word = /^\S*/.exec(tail)?.[0] ?? "";
  const trail = /[.,;:)\]]+$/.exec(word)?.[0] ?? "";
  const name = word.slice(0, word.length - trail.length);
  return `${name === "" ? "…" : `…${sep}${name}`}${trail}${tail.slice(word.length)}`;
}

/**
 * 글 속 로컬 절대 경로(`C:\…`·`\\서버\…`·`file://…` — 공백·한글·따옴표 안 포함)를 마지막 이름만 남긴
 * `…\이름`·`…/이름`으로 바꾼다. 워크스페이스 기준 상대 경로·https 주소는 그대로다
 */
export function hidePaths(text: string): string {
  return text
    // 자식 명령 출력의 터미널 색 코드는 화면에서 뺀다
    .replace(/\u001b\[[0-9;]*[A-Za-z]/g, "")
    .replace(FILE_URI, (uri) => shortenSpan(decodeURIComponentSafe(uri.slice("file://".length)), "/"))
    .replace(WIN_PATH, (p) => shortenSpan(p, "\\"));
}

/**
 * 구조화된 원천 값 하나(주소·경로): 원격 주소(https 등)는 그대로(인증 정보는 daemon이 가림), 로컬 경로·file://는
 * 값 전체를 경로로 보고 마지막 이름만. 워크스페이스 기준 상대 경로는 그대로
 */
function hideLocation(value: string, sep: "\\" | "/"): string {
  const isFile = /^file:\/\//i.test(value);
  if (!isFile && /^[a-z][a-z0-9+.-]*:\/\//i.test(value)) return hidePaths(value);
  const raw = isFile ? decodeURIComponentSafe(value.slice("file://".length)) : value;
  if (!isFile && !/^(?:[A-Za-z]:[\\/]|[\\/])/.test(raw)) return raw;
  const name = lastName(raw);
  return name === "" ? "…" : `…${sep}${name}`;
}

function decodeURIComponentSafe(s: string): string {
  try {
    return decodeURIComponent(s);
  } catch {
    return s;
  }
}

// ── 원천 ──────────────────────────────────────────────────────────

export interface SourceView {
  kind: "git" | "wheel" | "path" | "unknown";
  /** 종류 글 (Git·wheel·폴더) */
  label: string;
  /** 주소·경로 (가린 값) */
  where: string;
  /** git: "@ v0.1.0 (a1b2c3d)", wheel: "sha256 1a2b3c4d…" */
  detail: string | null;
}

function str(v: unknown): string | null {
  return typeof v === "string" && v !== "" ? v : null;
}

/** 잠금·미리보기의 원천(`source`)을 화면 글로 (git·wheel·path) */
export function sourceView(source: Record<string, unknown> | null | undefined): SourceView {
  const kind = str(source?.kind);
  if (kind === "git") {
    const ref = str(source?.ref);
    const commit = str(source?.commit);
    const parts = [ref !== null ? `@ ${ref}` : null, commit !== null ? `(${commit.slice(0, 7)})` : null].filter(Boolean);
    return { kind, label: "Git", where: hideLocation(str(source?.url) ?? "", "/"), detail: parts.length > 0 ? parts.join(" ") : null };
  }
  if (kind === "wheel") {
    const sha = str(source?.sha256);
    const url = str(source?.url);
    return {
      kind,
      label: "wheel",
      where: url !== null ? hideLocation(url, "/") : hideLocation(str(source?.path) ?? "", "\\"),
      detail: sha !== null ? `sha256 ${sha.slice(0, 12)}…` : null,
    };
  }
  if (kind === "path") return { kind, label: "폴더", where: hideLocation(str(source?.path) ?? "", "\\"), detail: null };
  return { kind: "unknown", label: kind ?? "?", where: "", detail: null };
}

// ── 추가 대화 상자 입력 ───────────────────────────────────────────

export type SourceKind = "git" | "wheel" | "path";

export interface SourceDraft {
  kind: SourceKind;
  text: string;
  ref: string;
  sha256: string;
  isolation: Isolation;
}

export const EMPTY_DRAFT: SourceDraft = { kind: "git", text: "", ref: "", sha256: "", isolation: "auto" };

/** ssh git 주소 (`ssh://`·`user@host:path`) — MVP는 받지 않는다 (M6 U14) */
export function isSshGit(text: string): boolean {
  const t = text.trim().replace(/^git\+/, "");
  return /^ssh:\/\//i.test(t) || /^[\w.-]+@[\w.-]+:(?!\/\/)/.test(t);
}

export const SSH_REFUSED =
  "ssh 주소는 아직 받지 않아요. 비공개 레포는 https 주소에 토큰을 넣어 주세요 (토큰은 잠금·로그·화면에 남지 않아요).";

/** 입력 → plugins.preview 인자. 틀리면 오류 문구 */
export function previewParams(draft: SourceDraft): { params: PreviewParams } | { error: string } {
  const text = draft.text.trim();
  const isolation = draft.isolation;
  if (draft.kind === "git") {
    if (text === "") return { error: "Git 주소를 넣어 주세요" };
    if (isSshGit(text)) return { error: SSH_REFUSED };
    const ref = draft.ref.trim();
    const source = text.startsWith("git+") ? text : `git+${text}`;
    return { params: { source, isolation, ...(ref !== "" ? { ref } : {}) } };
  }
  if (draft.kind === "wheel") {
    if (text === "") return { error: "wheel 파일 경로나 https 주소를 넣어 주세요" };
    if (/^http:\/\//i.test(text)) return { error: "wheel 주소는 https만 받아요" };
    const sha = draft.sha256.trim().toLowerCase();
    if (/^https:\/\//i.test(text) && !/^[0-9a-f]{64}$/.test(sha)) return { error: "https 주소면 sha256(64자리)이 필요해요" };
    return { params: { source: text, isolation, ...(sha !== "" ? { sha256: sha } : {}) } };
  }
  if (text === "") return { error: "플러그인 폴더 경로를 넣어 주세요" };
  return { params: { source: text, isolation } };
}

// ── 작업 진행·결과 ────────────────────────────────────────────────

const STEP_OF: Readonly<Record<string, string>> = {
  fetched: "받기",
  manifest: "받기",
  // 단계 이름은 "끝난 일"이다. confirmed·env_venv는 그 앞 단계가 끝났다는 뜻으로 본다
  confirmed: "받기",
  resolved: "의존성 풀기",
  built: "빌드",
  env_venv: "빌드",
  env_synced: "환경 만들기",
  env_installed: "환경 만들기",
  env_reused: "환경 만들기",
  env_verified: "확인",
  env_complete: "확인",
  archived: "잠금 바꾸기",
  before_commit: "잠금 바꾸기",
  committed: "잠금 바꾸기",
};

const STEPS: Readonly<Record<OpKind, readonly string[]>> = {
  install: ["받기", "의존성 풀기", "빌드", "환경 만들기", "확인", "잠금 바꾸기"],
  upgrade: ["받기", "의존성 풀기", "빌드", "환경 만들기", "확인", "잠금 바꾸기"],
  sync: ["환경 만들기", "확인"],
  relock: ["의존성 풀기", "환경 만들기", "확인", "잠금 바꾸기"],
  remove: ["환경 만들기", "확인", "잠금 바꾸기"],
  gc: [],
};

export interface StepView {
  label: string;
  state: "done" | "active" | "pending";
}

/**
 * 진행 단계 줄. 받은 거래 단계(`plugins.progress` stage) 중 마지막의 표시 단계까지 앞은 끝남, 그 다음 단계가
 * 진행 중. 미리보기를 거친 설치는 받기가 이미 끝났다. 끝났으면(`finished`) 모두 끝남
 */
export function progressSteps(kind: OpKind, stages: readonly string[], finished = false): StepView[] {
  const steps = STEPS[kind];
  let reached = kind === "install" || kind === "upgrade" ? 0 : -1;
  for (const stage of stages) {
    const at = steps.indexOf(STEP_OF[stage] ?? "");
    if (at > reached) reached = at;
  }
  // 단계 하나가 끝났다는 알림이 오면 다음 단계가 진행 중이다 (빌드가 없는 wheel·폴더 원천은 빌드를 건너뛴다)
  return steps.map((label, i) => ({
    label,
    state: finished || i <= reached ? "done" : i === reached + 1 ? "active" : "pending",
  }));
}

export const KIND_TEXT: Readonly<Record<OpKind, string>> = {
  install: "설치",
  upgrade: "업그레이드",
  remove: "제거",
  sync: "준비",
  relock: "다시 잠그기",
  gc: "정리",
};

const DONE_TEXT: Readonly<Record<OpKind, string>> = {
  install: "설치했어요",
  upgrade: "업그레이드했어요",
  remove: "제거했어요",
  sync: "준비했어요",
  relock: "다시 잠갔어요",
  gc: "안 쓰는 환경을 정리했어요",
};

const FAIL_TEXT: Readonly<Record<OpKind, string>> = {
  install: "설치하지 못했어요. 기존 플러그인은 그대로예요.",
  upgrade: "업그레이드하지 못했어요. 기존 플러그인은 그대로예요.",
  remove: "제거하지 못했어요. 플러그인은 그대로예요.",
  sync: "준비하지 못했어요. 잠금과 기존 환경은 그대로예요.",
  relock: "다시 잠그지 못했어요. 잠금은 그대로예요.",
  gc: "정리하지 못했어요. 쓰는 환경은 그대로예요.",
};

export function resultTitle(kind: OpKind, ok: boolean): string {
  return ok ? DONE_TEXT[kind] : FAIL_TEXT[kind];
}

const ERROR_TEXT: Readonly<Record<string, string>> = {
  source_unavailable: "원천을 받지 못했어요",
  source_refused: "이 주소·버전은 받을 수 없어요",
  manifest_invalid: "플러그인 정보가 올바르지 않아요",
  plugin_id_taken: "같은 ID의 플러그인이 이미 있어요",
  sdk_incompatible: "이 앱의 SDK와 맞지 않아요",
  core_too_old: "앱 판이 낮아요 — 앱을 올려 주세요",
  sdist_only_dependency: "wheel이 없는 의존성이 있어요 (소스 배포판만 있는 의존성은 설치하지 않아요)",
  build_failed: "플러그인을 빌드하지 못했어요",
  plugin_conflict: "의존성이 공유 환경과 충돌해요",
  resolve_failed: "의존성을 풀지 못했어요",
  env_create_failed: "환경을 만들지 못했어요",
  verify_failed: "설치한 플러그인을 확인하지 못했어요",
  plugin_busy: "다른 곳(다른 창·명령줄)에서 플러그인 작업이 진행 중이에요",
  revision_conflict: "그 사이 잠금 파일이 바뀌었어요 — 목록을 다시 보고 확인해 주세요",
  cancelled: "취소했어요",
  plugin_env_stale: "앱의 Python·SDK가 잠금과 달라요 — 다시 잠그기가 필요해요",
  op_not_found: "승인할 미리보기가 없어요 (5분이 지났거나 취소됐어요)",
  shutting_down: "daemon이 끝나는 중이에요",
};

export interface ErrorView {
  /** 사람이 읽는 요약 */
  summary: string;
  /** 자세히: 코드·단계·daemon 문구(경로 가림)·작업 로그 위치 */
  detail: string[];
}

/** 작업 오류(PluginErrorInfo)·요청 오류를 화면 글로. 원문은 작업 로그에 있다 */
export function errorView(error: { code?: string | null; stage?: string | null; message?: string; op_id?: string; conflicts?: string[] }): ErrorView {
  const code = error.code ?? "internal_error";
  let summary = ERROR_TEXT[code] ?? "작업이 실패했어요";
  if (code === "source_refused" && /ssh/i.test(error.message ?? "")) summary = SSH_REFUSED;
  if (code === "plugin_conflict" && (error.conflicts?.length ?? 0) > 0) summary += ` (${error.conflicts!.join(", ")})`;
  const detail = [`${code}${error.stage ? ` · 단계 ${error.stage}` : ""}`];
  if (error.message) detail.push(hidePaths(error.message));
  if (error.op_id) detail.push(`작업 로그: .kookabug/plugins/logs/${error.op_id}.log`);
  return { summary, detail };
}

// ── 목록 ──────────────────────────────────────────────────────────

export interface BannerView {
  kind: "prepare" | "relock";
  text: string;
  detail: string | null;
  count: number;
}

/** 준비 띠 (U2): 조건 다름이면 [다시 잠그기…], 환경 없음·깨짐이면 [준비…]. 잠금이 없거나 다 준비됐으면 null */
export function bannerView(list: PluginsList | null): BannerView | null {
  if (list === null || list.plugins.length === 0) return null;
  if (list.stale_reason !== null) {
    return {
      kind: "relock",
      text: "앱의 Python·SDK가 잠금과 달라요",
      detail: hidePaths(list.stale_reason),
      count: list.plugins.length,
    };
  }
  const missing = list.plugins.filter((p) => p.env_status === "missing" || p.env_status === "broken");
  if (missing.length === 0) return null;
  const broken = missing.some((p) => p.env_status === "broken");
  return {
    kind: "prepare",
    text: broken ? "환경이 깨졌어요 — 준비…로 새로 만들어요" : `준비 필요 ${missing.length}`,
    detail: broken ? null : "잠금은 있지만 이 PC에 환경이 없어요",
    count: missing.length,
  };
}

/** 주의가 필요한 플러그인 수 (액티비티 바 배지·상태 바 경고색) */
export function attentionCount(list: PluginsList | null): number {
  if (list === null) return 0;
  return list.plugins.filter((p) => p.env_status !== "ready").length;
}

/** "안 쓰는 환경 정리" 후보 요약. 지울 것이 없으면 null */
export function gcSummary(c: PluginsList["gc_candidates"] | undefined): string | null {
  if (c === undefined) return null;
  const parts = [
    c.envs.length > 0 ? `환경 ${c.envs.length}개` : null,
    c.wheels.length > 0 ? `wheel ${c.wheels.length}개` : null,
    c.staging.length > 0 ? `임시 폴더 ${c.staging.length}개` : null,
  ].filter((s): s is string => s !== null);
  return parts.length === 0 ? null : parts.join(" · ");
}

/** 다른 창·이 창 밖에서 진행 중인 작업 (busy). 이 창이 따라가는 작업이면 null */
export function busyText(busy: PluginsList["busy"] | undefined, mine: string | null): string | null {
  if (busy === null || busy === undefined) return null;
  if (mine !== null && busy.op_id === mine) return null;
  if (busy.waiting && busy.op_id === null) return "다른 창에서 신뢰 확인을 기다리는 중이에요";
  return `플러그인 ${KIND_TEXT[busy.kind]} 진행 중이에요`;
}

/** 플러그인 표시 이름 (manifest.title, 없으면 ID) */
export function pluginTitle(entry: Pick<PluginEntry, "id" | "manifest">): string {
  return str(entry.manifest.title) ?? entry.id;
}

export function pluginPermissions(entry: Pick<PluginEntry, "manifest">): string[] {
  const raw = entry.manifest.permissions;
  return Array.isArray(raw) ? raw.filter((p): p is string => typeof p === "string") : [];
}

/** 권한마다 그 권한을 쓰는 노드 (노드 effects) */
export function nodesByPermission(entry: Pick<PluginEntry, "nodes" | "manifest">): { id: string; nodes: string[] }[] {
  return pluginPermissions(entry).map((id) => ({
    id,
    nodes: entry.nodes.filter((n) => n.effects.includes(id)).map((n) => n.title ?? n.type),
  }));
}

/** 의존성 (SDK는 앱이 넣으므로 뺀다) */
export function dependencies(requires: readonly string[] | undefined): string[] {
  return (requires ?? []).filter((r) => !/^kookabug[-_]sdk\b/i.test(r.trim()));
}
