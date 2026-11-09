// 권한 설정 화면 (M5 계획 3.10 "권한 설정 화면", 시안 Permissions): 편집기 탭 "설정".
// 범위 사용자 / 프로젝트 / 팀(잠김 — 읽기만, kookabug.json에서 편집), 프리셋 4개, 툴셋 6줄(기본·허용·확인·거부),
// 세부 규칙 표(판정·규칙·출처, 추가·지우기), "사람 없는 실행" 안내문. 쓰기는 permissions.set 하나(revision)
import { useEffect, useState } from "react";
import { refreshPermissions as refreshAgentPermissions } from "../agent/agentStore";
import { client, toRpcError } from "../rpc/client";
import { openFileTab } from "../store/tabs";
import { useWorkspace } from "../store/workspace";
import { LockIcon } from "../theme/icons";
import css from "./settings.module.css";

type Info = Awaited<ReturnType<typeof load>>;
type Layer = NonNullable<Info["layers"]>[number];
type LayerName = "user" | "project" | "team";
type Verdict = "allow" | "ask" | "deny";

interface Perms {
  preset?: string;
  toolsets?: Record<string, Verdict>;
  rules?: { rule: string; verdict: Verdict }[];
}

export const PRESETS: [string, string][] = [
  ["graph_author", "그래프 작성 — 읽기 + 편집은 확인 후"],
  ["read_only", "읽기 전용"],
  ["runner", "실행 — 작성 + 실행, 입력은 확인 후"],
  // M7 3.11 U1: 조회·화면 지도 쓰기·탐색 세션 허용, 게임 조작 확인 후, 그래프 편집·실행 거부
  ["explorer", "탐색 — 화면 지도 쓰기, 게임 조작은 확인 후 (편집·실행 없음)"],
  // M8 3.14: 지식 관리(편집은 작업 기준에만), QA 실행(팀 기준 실행·사건 기록만)
  ["curator", "지식 관리 — 지식·사건·작업 기준 편집, 게임 조작은 확인 후"],
  ["qa_runner", "QA 실행 — 팀 기준 테스트 실행·사건 기록만 (편집·직접 조작 없음)"],
  ["full", "전체 (주의)"],
];

/** 툴셋 표시 이름 (U5: 확정 계약 이름 + 한국어) */
export const TOOLSETS: [string, string, string][] = [
  ["core", "기본", "프로젝트 정보, 그래프 읽기·검증, 실행 상태, 로그 검색 (늘 켜짐)"],
  ["graph_edit", "그래프 편집", "그래프 만들기, 노드·연결 패치, 대상 만들기"],
  ["run", "실행", "실행 시작·정지, 이벤트·증거·비교 읽기"],
  ["observe", "화면 보기", "캡처, 이미지 찾기, OCR (읽기만)"],
  ["control", "게임 조작", "게임 창에 클릭·키·글자 입력, 게임 실행"],
  ["screens", "화면 지도", "화면 지도 조회·식별, 탐색 세션과 후보 저장 (승격·버리기는 사람만)"],
  ["knowledge", "지식", "주장·경험칙·치트 후보·미지수 읽기와 제한 연산, 위키 쓰기"],
  ["cases", "사건", "사건 열기·고치기·조사 신호, 증거 고정, 자동 채택 요청, 보고 메모"],
];

const VERDICT_TEXT: Record<Verdict, string> = { allow: "허용", ask: "확인", deny: "거부" };
const LAYER_TEXT: Record<LayerName, string> = { user: "사용자", project: "프로젝트", team: "팀" };

async function load() {
  return client().call("permissions.get", {});
}

const VERDICTS = new Set(["allow", "ask", "deny"]);
const PRESET_IDS = new Set(PRESETS.map(([id]) => id));
const TOOLSET_IDS = new Set(TOOLSETS.map(([id]) => id));

/**
 * 계층 파일의 permissions 값을 형식대로 읽는다 (검수 B5 M1). 틀리면 null — 화면은 진단을 보이고 그 계층 편집을
 * 막는다(파일은 그대로). 값이 없으면 빈 객체
 */
export function parsePerms(raw: unknown): Perms | null {
  if (raw === null || raw === undefined) return {};
  if (typeof raw !== "object" || Array.isArray(raw)) return null;
  const v = raw as Record<string, unknown>;
  for (const key of Object.keys(v)) if (!["preset", "toolsets", "rules"].includes(key)) return null;
  if (v.preset !== undefined && !(typeof v.preset === "string" && PRESET_IDS.has(v.preset))) return null;
  if (v.toolsets !== undefined) {
    if (typeof v.toolsets !== "object" || v.toolsets === null || Array.isArray(v.toolsets)) return null;
    for (const [k, x] of Object.entries(v.toolsets)) if (!TOOLSET_IDS.has(k) || typeof x !== "string" || !VERDICTS.has(x)) return null;
  }
  if (v.rules !== undefined) {
    if (!Array.isArray(v.rules)) return null;
    for (const r of v.rules) {
      if (typeof r !== "object" || r === null) return null;
      const rule = r as Record<string, unknown>;
      if (typeof rule.rule !== "string" || typeof rule.verdict !== "string" || !VERDICTS.has(rule.verdict)) return null;
    }
  }
  return v as Perms;
}

function permsOf(layer: Layer | undefined): Perms {
  return parsePerms(layer?.permissions) ?? {};
}

function VerdictSelect({
  label,
  value,
  disabled,
  withDefault,
  onChange,
}: {
  label: string;
  value: Verdict | "";
  disabled: boolean;
  withDefault: boolean;
  onChange(v: Verdict | ""): void;
}) {
  return (
    <select
      aria-label={label}
      className={css.select}
      data-verdict={value}
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value as Verdict | "")}
    >
      {withDefault && <option value="">기본 (프리셋)</option>}
      <option value="allow">허용</option>
      <option value="ask">확인</option>
      <option value="deny">거부</option>
    </select>
  );
}

export function PermissionsView() {
  const name = useWorkspace((s) => s.name);
  const connected = useWorkspace((s) => s.daemon.status === "connected");
  const [info, setInfo] = useState<Info | null>(null);
  const [scope, setScope] = useState<LayerName>("project");
  const [message, setMessage] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [newRule, setNewRule] = useState("");
  const [newVerdict, setNewVerdict] = useState<Verdict>("deny");

  const reload = async () => {
    try {
      setInfo(await load());
    } catch (err) {
      setMessage(`권한 설정을 읽지 못했어요: ${toRpcError(err).message}`);
    }
  };
  useEffect(() => {
    if (connected) void reload();
  }, [connected]);

  const layers = info?.layers ?? [];
  const layer = layers.find((l) => l.layer === scope);
  const perms = permsOf(layer);
  const malformed = layer !== undefined && parsePerms(layer.permissions) === null;
  const hasError = (layer?.diagnostics ?? []).some((d) => d.severity === "error");
  const editable = layer?.editable === true && !malformed && !hasError;
  // 다른 범위의 형식 오류도 맨 위에 알린다 (그 계층 값은 판정에서도 거부된다)
  const brokenLayers = layers
    .filter((l) => l.layer !== scope && (parsePerms(l.permissions) === null || (l.diagnostics ?? []).some((d) => d.severity === "error")))
    .map((l) => LAYER_TEXT[l.layer as LayerName]);

  async function write(next: Perms): Promise<void> {
    if (layer === undefined || !editable) return;
    setSaving(true);
    setMessage(null);
    try {
      await client().call("permissions.set", {
        layer: scope as "user" | "project",
        permissions: next as Record<string, unknown>,
        base_revision: layer.revision ?? null,
      });
    } catch (err) {
      const e = toRpcError(err);
      setMessage(
        e.kind === "revision_conflict"
          ? "그 사이 파일이 바뀌어 저장하지 않았어요. 다시 읽었어요."
          : e.kind === "settings_invalid"
            ? `파일 형식이 틀려 고치지 않았어요: ${e.message}`
            : `저장하지 못했어요: ${e.message}`,
      );
    }
    setSaving(false);
    await reload();
    void refreshAgentPermissions();
  }

  const setPreset = (preset: string) => {
    const next: Perms = { ...perms };
    if (preset === "") delete next.preset;
    else next.preset = preset;
    void write(next);
  };
  const setToolset = (id: string, v: Verdict | "") => {
    const toolsets = { ...(perms.toolsets ?? {}) };
    if (v === "") delete toolsets[id];
    else toolsets[id] = v;
    const next: Perms = { ...perms, toolsets };
    if (Object.keys(toolsets).length === 0) delete next.toolsets;
    void write(next);
  };
  const removeRule = (index: number) => {
    const rules = (perms.rules ?? []).filter((_, i) => i !== index);
    const next: Perms = { ...perms, rules };
    if (rules.length === 0) delete next.rules;
    void write(next);
  };
  const addRule = () => {
    const rule = newRule.trim();
    if (rule === "") return;
    void write({ ...perms, rules: [...(perms.rules ?? []), { rule, verdict: newVerdict }] }).then(() => setNewRule(""));
  };

  // 모든 계층의 규칙 (판정 순서: 거부 → 확인 → 허용)
  const order: Record<Verdict, number> = { deny: 0, ask: 1, allow: 2 };
  const allRules = layers
    .flatMap((l) => (permsOf(l).rules ?? []).map((r, i) => ({ ...r, layer: l.layer as LayerName, index: i })))
    .sort((a, b) => order[a.verdict] - order[b.verdict]);
  const preset = perms.preset ?? "";

  return (
    <div className={css.settings} data-part="permissions-view" data-scope={scope}>
      <div className={css.scopes} role="tablist" aria-label="설정 범위">
        {(["user", "project", "team"] as const).map((s) => (
          <button
            key={s}
            type="button"
            role="tab"
            aria-selected={scope === s}
            className={css.scope}
            data-scope={s}
            onClick={() => setScope(s)}
          >
            {s === "team" && <LockIcon />}
            {s === "project" ? `프로젝트 · ${name ?? ""}` : s === "team" ? "팀 (잠김)" : LAYER_TEXT[s]}
          </button>
        ))}
        <div className={css.spacer} />
        <button type="button" className={css.link} onClick={() => openFileTab("kookabug.json")}>
          kookabug.json에서 편집
        </button>
      </div>
      <div className={css.content}>
        <h2 className={css.h2}>에이전트 · 권한</h2>
        {layer?.source && (
          <div className={css.source} data-part="layer-source">
            {scope === "team" ? "팀 설정은 여기서 고치지 않아요 (읽기만). " : ""}
            {layer.source}
          </div>
        )}
        {(layer?.diagnostics ?? []).map((d, i) => (
          <div key={i} className={css.message} role="alert">
            {d.message}
          </div>
        ))}
        {brokenLayers.length > 0 && (
          <div className={css.message} role="alert" data-part="other-layer-broken">
            {brokenLayers.join("·")} 계층 설정 형식이 틀렸어요. 그 범위를 열어 확인해 주세요.
          </div>
        )}
        {malformed && (
          <div className={css.message} role="alert" data-part="layer-malformed">
            이 계층의 permissions 형식이 틀려 여기서 고치지 않아요. 파일을 직접 고친 뒤 다시 열어 주세요 (파일은 그대로예요).
          </div>
        )}
        {message !== null && (
          <div className={css.message} role="alert" data-part="settings-message">
            {message}
          </div>
        )}

        <div className={css.item} data-modified={preset !== ""}>
          <div>
            <span className={css.crumb}>에이전트 › 권한: </span>
            <b className={css.itemTitle}>프리셋</b> {preset !== "" && <span className={css.note}>· 수정됨</span>}
          </div>
          <div className={css.desc}>에이전트에게 기본으로 줄 권한 묶음입니다. 아래 툴셋별 값이 프리셋보다 우선합니다.</div>
          <select
            aria-label="프리셋"
            className={`${css.select} ${css.wide}`}
            value={preset}
            disabled={!editable || saving}
            onChange={(e) => setPreset(e.target.value)}
          >
            <option value="">설정 안 함 (다음 계층·기본값)</option>
            {PRESETS.map(([v, label]) => (
              <option key={v} value={v}>
                {label}
              </option>
            ))}
          </select>
        </div>

        {TOOLSETS.map(([id, label, desc]) => {
          const value = perms.toolsets?.[id] ?? "";
          return (
            <div key={id} className={css.item} data-modified={value !== ""} data-part="toolset-row" data-toolset={id}>
              <div>
                <span className={css.crumb}>에이전트 › 권한 › 툴셋: </span>
                <b className={css.itemTitle}>{label}</b> <span className={css.mono}>{id}</span>
                {value !== "" && <span className={css.note}> · 수정됨</span>}
              </div>
              <div className={css.desc}>{desc}</div>
              <VerdictSelect
                label={`${id} 권한`}
                value={value}
                withDefault
                disabled={!editable || saving}
                onChange={(v) => setToolset(id, v)}
              />
            </div>
          );
        })}

        <div className={css.item} data-modified={(perms.rules ?? []).length > 0}>
          <div>
            <span className={css.crumb}>에이전트 › 권한: </span>
            <b className={css.itemTitle}>세부 규칙</b>
          </div>
          <div className={css.desc}>
            <span className={css.mono}>도구(인자 패턴)</span> 형식입니다. 거부 → 확인 → 허용 순서로 적용됩니다. 팀 거부 규칙은 늘
            이깁니다.
          </div>
          <div className={css.tableWrap}>
            <table className={css.table} data-part="rules-table">
              <thead>
                <tr>
                  <th>판정</th>
                  <th>규칙</th>
                  <th>출처</th>
                  <th aria-label="지우기" />
                </tr>
              </thead>
              <tbody>
                {allRules.length === 0 && (
                  <tr>
                    <td colSpan={4} className={css.desc}>
                      규칙이 없어요
                    </td>
                  </tr>
                )}
                {allRules.map((r) => (
                  <tr key={`${r.layer}:${r.index}`} data-part="rule-row" data-layer={r.layer}>
                    <td data-verdict={r.verdict} className={css.verdict}>
                      {VERDICT_TEXT[r.verdict]}
                    </td>
                    <td className={css.mono}>{r.rule}</td>
                    <td className={css.desc}>{r.layer === "team" ? "팀 (잠김)" : LAYER_TEXT[r.layer]}</td>
                    <td>
                      {r.layer === scope && editable && (
                        <button type="button" className={css.link} aria-label={`${r.rule} 지우기`} onClick={() => removeRule(r.index)}>
                          지우기
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {editable && (
            <div className={css.addRow}>
              <VerdictSelect label="새 규칙 판정" value={newVerdict} withDefault={false} disabled={saving} onChange={(v) => setNewVerdict(v as Verdict)} />
              <input
                aria-label="새 규칙"
                className={`${css.input} ${css.mono}`}
                placeholder="kb_input_*(SampleRPG*)"
                value={newRule}
                onChange={(e) => setNewRule(e.target.value)}
              />
              <button type="button" className={css.primary} disabled={saving || newRule.trim() === ""} onClick={addRule}>
                규칙 추가
              </button>
            </div>
          )}
        </div>

        <div className={css.item}>
          <div>
            <span className={css.crumb}>에이전트 › 권한: </span>
            <b className={css.itemTitle}>사람 없는 실행</b>
          </div>
          <div className={css.desc}>
            사람이 지켜보지 않는 연결(<span className={css.mono}>kookabug mcp --unattended</span>, 야간·CI 실행의 Agent 판단 노드)에서는
            "확인"을 "거부"로 처리합니다. 앱이 열려 있지 않으면 확인할 사람이 없어 거부됩니다.
          </div>
          <div className={css.desc}>
            권한은 Kookabug 서버(daemon)를 거치는 동작에만 적용됩니다. 에이전트 자체 도구(파일 편집·셸)는 에이전트 쪽 확인을
            따릅니다.
          </div>
        </div>
      </div>
    </div>
  );
}
