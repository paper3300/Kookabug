// 속성 편집기 입력 상자 (M2 계획 2.11): 숫자 상자·한 줄 상자·확인란·선택 상자·점/사각형 칸·줄 편집·JSON 상자와
// 특수 값(연결·대상·설정·비밀·그대로 넣은 값) 보기. 글자 입력은 Enter·포커스를 떠날 때 한 번 반영한다(실행 취소
// 하나). 틀린 값은 바로 아래에 알리고 반영하지 않는다. Esc는 고치던 글자를 버린다
import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { own, specialTag } from "../graph/model";
import { loadSecrets, useRecorder } from "../recorder/recorderStore";
import { useWorkspace } from "../store/workspace";
import {
  CELL_NAMES,
  dictFromEntries,
  editorFor,
  emptyElement,
  fits,
  formatJson,
  formatNumber,
  linkText,
  moveItem,
  parseCells,
  parseJson,
  parseNumber,
  valueModeFor,
  type FieldEditor,
  type FieldSpec,
  type Parsed,
} from "./fields";
import css from "./inspector.module.css";

export interface EditorContext {
  locked: boolean;
  /** 노드 ID → 보이는 제목 (연결 표시) */
  titleOf(id: string): string;
  /** false면 특수 값을 해석하지 않는다 (config 칸과 그 안쪽 원소). 없으면 true */
  specials?: boolean;
  /** 고치는 그래프 경로 ("새 대상 만들기"가 저장 뒤 그 핀을 채운다) */
  graph?: string;
}

/** 고치는 중인 글자 (null이면 값에서 만든 글자를 보인다) */
function useDraft(): [string | null, (t: string | null) => void] {
  return useState<string | null>(null);
}

export interface EditKeys {
  /** Enter(여러 줄이면 Ctrl+Enter) = 반영, Esc = 고치던 글자를 버리고 칸을 떠난다 */
  onKeyDown(commit: () => void, reset: () => void, multiline?: boolean): (e: KeyboardEvent<HTMLElement>) => void;
  /** 칸을 떠나면 반영한다. Esc로 떠나는 blur는 반영하지 않는다 */
  onBlur(commit: () => void): () => void;
}

/**
 * Esc 취소 막이. blur는 `element.blur()` 안에서 바로(동기로) 오고, 그때 commit은 아직 앞 렌더의 고치던 글자를
 * 든다(상태 갱신이 반영되기 전). 그래서 Esc로 떠나는 동안은 표시를 세워 그 blur의 반영을 막는다 (T10 검수 1)
 */
export function useEditKeys(): EditKeys {
  const cancelling = useRef(false);
  return {
    onKeyDown: (commit, reset, multiline = false) => (e) => {
      if (e.key === "Enter" && (!multiline || e.ctrlKey)) {
        e.preventDefault();
        commit();
      } else if (e.key === "Escape") {
        e.preventDefault();
        cancelling.current = true;
        try {
          reset();
          (e.currentTarget as HTMLElement).blur();
        } finally {
          cancelling.current = false;
        }
      }
    },
    onBlur: (commit) => () => {
      if (!cancelling.current) commit();
    },
  };
}

export function FieldError({ error }: { error: string | null }) {
  if (error === null) return null;
  return (
    <div role="alert" className={css.fieldError} data-part="field-error">
      {error}
    </div>
  );
}

/** 글자를 고쳐 반영하는 한 줄 상자. parse가 틀리면 알리고 반영하지 않는다 */
function ParsedInput<T>({
  label,
  shown,
  placeholder,
  parse,
  onCommit,
  ctx,
  mono,
  list,
}: {
  label: string;
  shown: string;
  placeholder?: string;
  parse(text: string): Parsed<T>;
  onCommit(v: T): void;
  ctx: EditorContext;
  mono?: boolean;
  /** 제안 목록 datalist id (자유 입력은 그대로) */
  list?: string;
}) {
  const [draft, setDraft] = useDraft();
  const keys = useEditKeys();
  const result = draft === null ? null : parse(draft);
  const commit = () => {
    if (draft === null || draft === shown) {
      setDraft(null);
      return;
    }
    if (result !== null && result.ok) {
      onCommit(result.value);
      setDraft(null);
    }
  };
  return (
    <>
      <label className={`${css.box} ${result !== null && !result.ok ? css.boxInvalid : ""}`}>
        <input
          aria-label={label}
          aria-invalid={result !== null && !result.ok}
          className={mono ? css.mono : undefined}
          value={draft ?? shown}
          placeholder={placeholder}
          list={list}
          disabled={ctx.locked}
          spellCheck={false}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={keys.onBlur(commit)}
          onKeyDown={keys.onKeyDown(commit, () => setDraft(null))}
        />
      </label>
      <FieldError error={result !== null && !result.ok && draft !== shown ? result.error : null} />
    </>
  );
}

function placeholderOf(spec: Pick<FieldSpec, "default" | "required"> | undefined): string {
  if (spec === undefined) return "";
  if (spec.default !== undefined) return `기본값 ${formatJson(spec.default)}`;
  return spec.required ? "필수" : "비어 있음";
}

/** 점·사각형 칸 (정수 픽셀). 칸을 다 채우면 반영한다 */
function CellsInput({
  label,
  kind,
  value,
  onCommit,
  ctx,
}: {
  label: string;
  kind: "point" | "rect";
  value: unknown;
  onCommit(v: number[]): void;
  ctx: EditorContext;
}) {
  const names = CELL_NAMES[kind];
  const shown = names.map((_, i) => (Array.isArray(value) && typeof value[i] === "number" ? formatNumber(value[i]) : ""));
  const [draft, setDraft] = useState<string[] | null>(null);
  const keys = useEditKeys();
  const cells = draft ?? shown;
  const result = draft === null ? null : parseCells(cells, kind);
  const commit = () => {
    if (draft === null || draft.every((c, i) => c === shown[i])) {
      setDraft(null);
      return;
    }
    if (result !== null && result.ok) {
      onCommit(result.value);
      setDraft(null);
    }
  };
  return (
    <>
      <div className={css.cells} data-part={`cells-${kind}`}>
        {names.map((n, i) => (
          <label key={n} className={`${css.box} ${css.cell}`}>
            <span className={css.cellName}>{n}</span>
            <input
              aria-label={`${label} ${n}`}
              value={cells[i]}
              disabled={ctx.locked}
              inputMode="numeric"
              onChange={(e) => setDraft(cells.map((c, j) => (j === i ? e.target.value : c)))}
              onBlur={(e) => {
                // 칸 사이를 옮겨 다니는 동안은 반영하지 않는다
                const inside = e.relatedTarget instanceof HTMLElement && e.currentTarget.closest(`.${css.cells}`)?.contains(e.relatedTarget);
                if (!inside) keys.onBlur(commit)();
              }}
              onKeyDown={keys.onKeyDown(commit, () => setDraft(null))}
            />
          </label>
        ))}
      </div>
      <FieldError error={result !== null && !result.ok ? result.error : null} />
    </>
  );
}

/** JSON 상자. 여러 줄이면 Ctrl+Enter 또는 포커스를 떠날 때 반영 */
export function JsonInput({
  label,
  value,
  onCommit,
  ctx,
  rows,
  parse = parseJson,
  placeholder,
}: {
  label: string;
  value: unknown;
  onCommit(v: unknown): void;
  ctx: EditorContext;
  rows?: number;
  parse?(text: string): Parsed<unknown>;
  placeholder?: string;
}) {
  const multiline = (rows ?? 1) > 1 || (typeof value === "object" && value !== null);
  const shown = value === undefined ? "" : formatJson(value, multiline ? 2 : 0);
  const [draft, setDraft] = useDraft();
  const keys = useEditKeys();
  const result = draft === null ? null : parse(draft);
  const commit = () => {
    if (draft === null || draft === shown) {
      setDraft(null);
      return;
    }
    if (result !== null && result.ok) {
      onCommit(result.value);
      setDraft(null);
    }
  };
  const text = draft ?? shown;
  return (
    <>
      <textarea
        aria-label={label}
        aria-invalid={result !== null && !result.ok}
        className={`${css.textarea} ${result !== null && !result.ok ? css.boxInvalid : ""}`}
        rows={rows ?? Math.min(12, Math.max(1, text.split("\n").length))}
        value={text}
        placeholder={placeholder}
        disabled={ctx.locked}
        spellCheck={false}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={keys.onBlur(commit)}
        onKeyDown={keys.onKeyDown(commit, () => setDraft(null), multiline)}
      />
      <FieldError error={result !== null && !result.ok ? result.error : null} />
    </>
  );
}

/** 대상 고르기: 워크스페이스의 *.target.json. onCreate가 있으면 "새 대상 만들기" (target 편집기, TargetField.tsx) */
export function TargetSelect({
  label,
  value,
  onCommit,
  ctx,
  onCreate,
}: {
  label: string;
  value: string;
  onCommit(path: string): void;
  ctx: EditorContext;
  onCreate?: () => void;
}) {
  const entries = useWorkspace((s) => s.entries);
  const targets = entries.filter((e) => e.type === "file" && e.kind === "target").map((e) => e.path);
  const missing = value !== "" && !targets.includes(value);
  return (
    <div className={css.row}>
      <label className={`${css.box} ${css.grow}`}>
        <select
          aria-label={label}
          value={value}
          disabled={ctx.locked}
          onChange={(e) => e.target.value !== "" && onCommit(e.target.value)}
        >
          <option value="" disabled>
            대상 고르기…
          </option>
          {missing && <option value={value}>{value} (없음)</option>}
          {targets.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </label>
      {onCreate !== undefined && (
        <button
          type="button"
          className={css.button}
          data-part="new-target"
          disabled={ctx.locked}
          title="target 편집기에서 새 대상을 만들고, 저장하면 이 칸에 넣어요"
          onClick={onCreate}
        >
          새 대상 만들기
        </button>
      )}
    </div>
  );
}

/** 설정·비밀 키 (`$setting`·`$secret`) */
export function KeyInput({
  label,
  tag,
  value,
  onCommit,
  ctx,
}: {
  label: string;
  tag: "$setting" | "$secret";
  value: string;
  onCommit(key: string): void;
  ctx: EditorContext;
}) {
  const kind = tag === "$setting" ? "설정" : "비밀";
  const secret = tag === "$secret";
  // $secret 제안: 자격 증명 관리자의 이 워크스페이스 키 (secrets.list, 값 없음 — M4 B2 인계). 자유 입력 유지
  const keys = useRecorder((s) => s.secrets);
  useEffect(() => {
    if (secret) void loadSecrets();
  }, [secret]);
  const listId = `kb-secret-keys-${label.replace(/[^A-Za-z0-9_-]/g, "_")}`;
  return (
    <div className={css.keyRow} data-part="key-input" data-tag={tag}>
      <span className={`${css.chip} ${tag === "$secret" ? css.chipSecret : css.chipSetting}`}>{kind}</span>
      <div className={css.grow}>
        <ParsedInput
          label={`${label} ${kind} 키`}
          shown={value}
          placeholder={`${kind} 키 (예: ${tag === "$setting" ? "game.title" : "accounts.qa"})`}
          parse={(t) => (t.trim() === "" ? { ok: false, error: "키를 넣으세요" } : { ok: true, value: t.trim() })}
          onCommit={onCommit}
          ctx={ctx}
          mono
          list={secret ? listId : undefined}
        />
        {secret && (
          <datalist id={listId} data-part="secret-key-suggestions">
            {keys.map((k) => (
              <option key={k.key} value={k.key}>
                {k.key} (자격 증명 관리자)
              </option>
            ))}
          </datalist>
        )}
      </div>
    </div>
  );
}

export function LinkView({
  value,
  ctx,
  onDisconnect,
}: {
  value: unknown;
  ctx: EditorContext;
  onDisconnect?: () => void;
}) {
  const link = linkText(value);
  return (
    <div className={css.row}>
      <div className={`${css.readonly} ${css.grow}`} data-part="link">
        <span aria-hidden="true">← </span>
        {link === null ? formatJson(value) : (
          <>
            <b className={css.linkNode}>{ctx.titleOf(link.node)}</b>.{link.output}
          </>
        )}
      </div>
      {onDisconnect !== undefined && (
        <button type="button" className={css.button} disabled={ctx.locked} onClick={onDisconnect}>
          연결 끊기
        </button>
      )}
    </div>
  );
}

/** `$literal`: 안을 해석하지 않고 그대로 보여 준다 */
export function LiteralView({ value }: { value: unknown }) {
  return (
    <div className={css.readonly} data-part="literal">
      <span className={css.chip}>그대로 넣은 값</span>
      <pre className={css.pre}>{formatJson(own(value, "$literal"), 2)}</pre>
    </div>
  );
}

/** 상수 입력. 값이 그 모양에 맞지 않으면 JSON 상자로 보여 값을 잃지 않는다 */
export function ConstantEditor({
  editor,
  spec,
  label,
  value,
  onCommit,
  ctx,
}: {
  editor: FieldEditor;
  spec?: FieldSpec;
  label: string;
  value: unknown;
  onCommit(v: unknown): void;
  ctx: EditorContext;
}) {
  const kind = value === undefined || fits(editor.kind, value) ? editor.kind : "json";
  const placeholder = placeholderOf(spec);
  switch (kind) {
    case "number":
      return (
        <ParsedInput
          label={label}
          shown={typeof value === "number" ? formatNumber(value) : ""}
          placeholder={placeholder}
          parse={(t) => parseNumber(t, { integer: editor.integer, minimum: spec?.minimum, maximum: spec?.maximum })}
          onCommit={onCommit}
          ctx={ctx}
          mono
        />
      );
    case "text":
      return (
        <ParsedInput
          label={label}
          shown={typeof value === "string" ? value : ""}
          placeholder={placeholder}
          parse={(t) => ({ ok: true, value: t })}
          onCommit={onCommit}
          ctx={ctx}
        />
      );
    case "bool": {
      const checked = typeof value === "boolean" ? value : spec?.default === true;
      return (
        <label className={css.check}>
          <input
            type="checkbox"
            aria-label={label}
            checked={checked}
            disabled={ctx.locked}
            onChange={() => onCommit(!checked)}
          />
          <span className={value === undefined ? css.muted : undefined}>
            {checked ? "켬" : "끔"}
            {value === undefined ? " (기본값)" : ""}
          </span>
        </label>
      );
    }
    case "enum": {
      const options = spec?.enum ?? [];
      const index = value === undefined ? -1 : options.findIndex((o) => formatJson(o) === formatJson(value));
      return (
        <label className={css.box}>
          <select
            aria-label={label}
            value={index >= 0 ? String(index) : value === undefined ? "" : "current"}
            disabled={ctx.locked}
            onChange={(e) => {
              const i = Number(e.target.value);
              if (e.target.value !== "" && e.target.value !== "current" && i >= 0) onCommit(options[i]);
            }}
          >
            {value === undefined && (
              <option value="" disabled>
                {placeholder}
              </option>
            )}
            {value !== undefined && index < 0 && <option value="current">{formatJson(value)} (목록에 없음)</option>}
            {options.map((o, i) => (
              <option key={i} value={String(i)}>
                {typeof o === "string" ? o : formatJson(o)}
              </option>
            ))}
          </select>
        </label>
      );
    }
    case "point":
    case "rect":
      return <CellsInput label={label} kind={kind} value={value} onCommit={onCommit} ctx={ctx} />;
    case "list":
    case "dict":
      return (
        <ListEditor label={label} dict={kind === "dict"} element={editor.element} value={value} onCommit={onCommit} ctx={ctx} />
      );
    default:
      return <JsonInput label={label} value={value} onCommit={onCommit} ctx={ctx} placeholder={placeholder} />;
  }
}

/** 목록·사전의 원소 하나: 특수 값이면 그 보기, 아니면 원소 타입의 상수 입력 */
function ElementEditor({
  label,
  type,
  value,
  onCommit,
  ctx,
}: {
  label: string;
  type: string;
  value: unknown;
  onCommit(v: unknown): void;
  ctx: EditorContext;
}) {
  const specials = ctx.specials !== false;
  const editor = editorFor({ type }, { specials });
  const mode = valueModeFor(value, specials);
  if (mode === "link") return <LinkView value={value} ctx={ctx} />;
  if (mode === "literal") return <LiteralView value={value} />;
  if (mode === "linked-inside") return <div className={`${css.readonly} ${css.mono}`}>{formatJson(value)}</div>;
  const tag = specialTag(value);
  if (mode === "target" || (specials && editor.kind === "target" && value === null)) {
    const inner = own(value, "$target");
    return (
      <TargetSelect label={label} value={typeof inner === "string" ? inner : ""} onCommit={(p) => onCommit({ $target: p })} ctx={ctx} />
    );
  }
  if ((mode === "setting" || mode === "secret") && (tag === "$setting" || tag === "$secret")) {
    const inner = own(value, tag);
    return <KeyInput label={label} tag={tag} value={typeof inner === "string" ? inner : ""} onCommit={(k) => onCommit({ [tag]: k })} ctx={ctx} />;
  }
  const constant = editor.kind === "target" || editor.kind === "secret" || editor.kind === "link-only" ? { ...editor, kind: "json" as const } : editor;
  return <ConstantEditor editor={constant} label={label} value={value} onCommit={onCommit} ctx={ctx} />;
}

function uniqueKey(keys: readonly string[]): string {
  let i = keys.length + 1;
  while (keys.includes(`key${i}`)) i++;
  return `key${i}`;
}

/** 줄 편집 (list·dict): 줄마다 원소 입력, 순서 바꾸기 ↑↓, 지우기, 추가 */
function ListEditor({
  label,
  dict,
  element,
  value,
  onCommit,
  ctx,
}: {
  label: string;
  dict: boolean;
  element: string | null;
  value: unknown;
  onCommit(v: unknown): void;
  ctx: EditorContext;
}) {
  const entries: [string, unknown][] = dict
    ? value !== null && typeof value === "object" && !Array.isArray(value)
      ? Object.keys(value).map((k) => [k, (value as Record<string, unknown>)[k]])
      : []
    : Array.isArray(value)
      ? value.map((x, i) => [String(i), x])
      : [];
  const emit = (next: [string, unknown][]) => onCommit(dict ? dictFromEntries(next) : next.map(([, v]) => v));
  const type = element ?? "any";
  const rows: ReactNode[] = entries.map(([k, v], i) => {
    const rowLabel = dict ? `${label} ${k}` : `${label} ${i + 1}`;
    return (
      <div key={dict ? `k:${k}` : `i:${i}`} className={css.listRow} data-part="list-row" data-key={k}>
        {dict && (
          <div className={css.listKey}>
            <ParsedInput
              label={`${label} 키 ${k}`}
              shown={k}
              parse={(t) =>
                t === "" ? { ok: false, error: "키를 넣으세요" } : t !== k && entries.some(([x]) => x === t) ? { ok: false, error: "같은 키가 있어요" } : { ok: true, value: t }
              }
              onCommit={(nk) => emit(entries.map(([x, y]) => (x === k ? [nk, y] : [x, y])))}
              ctx={ctx}
              mono
            />
          </div>
        )}
        <div className={css.listValue}>
          <ElementEditor
            label={rowLabel}
            type={type}
            value={v}
            onCommit={(nv) => emit(entries.map(([x, y], j) => (j === i ? [x, nv] : [x, y])))}
            ctx={ctx}
          />
        </div>
        <div className={css.listActions}>
          <button
            type="button"
            aria-label={`${rowLabel} 위로`}
            className={css.iconButton}
            disabled={ctx.locked || i === 0}
            onClick={() => emit(moveItem(entries, i, i - 1))}
          >
            ↑
          </button>
          <button
            type="button"
            aria-label={`${rowLabel} 아래로`}
            className={css.iconButton}
            disabled={ctx.locked || i === entries.length - 1}
            onClick={() => emit(moveItem(entries, i, i + 1))}
          >
            ↓
          </button>
          <button
            type="button"
            aria-label={`${rowLabel} 지우기`}
            className={css.iconButton}
            disabled={ctx.locked}
            onClick={() => emit(entries.filter((_, j) => j !== i))}
          >
            ×
          </button>
        </div>
      </div>
    );
  });
  return (
    <div className={css.list} data-part="list">
      {rows}
      {entries.length === 0 && <div className={css.muted}>비어 있음</div>}
      <button
        type="button"
        className={css.addButton}
        disabled={ctx.locked}
        aria-label={`${label} 추가`}
        onClick={() => emit([...entries, [dict ? uniqueKey(entries.map(([x]) => x)) : String(entries.length), emptyElement(element)]])}
      >
        + 추가
      </button>
    </div>
  );
}
