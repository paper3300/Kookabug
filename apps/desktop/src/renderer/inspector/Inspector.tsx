// 속성 편집기 (M2 계획 2.11, T10, U1): 오른쪽 패널(에이전트 패널 자리, 폭 320px, 접기 가능). 사이드바와 같은 섹션
// 머리·입력 상자 모양이다. 고른 노드(문서 보기 상태의 주 노드)의 제목·입력 핀·config를 고친다.
// - 고치기는 문서 표의 applyEdit 하나로만 한다 (편집 잠금·실행 취소 기록·검증 요청이 함께 된다, T9 인계)
// - 핀 모양은 daemon 결과다. config 배열(동적 출구)을 고치면 검증 응답으로 출구 핀이 바뀐다. 이름이 바뀌어 끊긴
//   next는 그대로 두고 문제 패널에 나오게 한다
// - 모르는 노드는 in·config를 JSON 상자로 보여 주고, 고치면 바뀐 키만 바꾼다
import { useState } from "react";
import { clearNodeValue, disconnect, replaceNodeObject, setNodeTitle, setNodeValue, type NodeField } from "../graph/commands";
import { graphNodes, own, type Diagnostic, type GraphValue } from "../graph/model";
import { useEditsLocked } from "../store/dialog";
import { applyEdit, useDocuments } from "../store/documents";
import { useRegistry } from "../store/registry";
import { useTabs } from "../store/tabs";
import { useUi } from "../store/ui";
import { ChevronDownIcon, ChevronRightIcon } from "../theme/icons";
import {
  useEditKeys,
  ConstantEditor,
  JsonInput,
  KeyInput,
  LinkView,
  LiteralView,
  type EditorContext,
} from "./editors";
import { TargetField } from "./TargetField";
import { editorFor, formatJson, parseJsonObject, valueModeFor, type FieldSpec } from "./fields";
import css from "./inspector.module.css";
import { inspectNode, type NodeInspector } from "./model";

type Choice = "value" | "setting" | "secret" | "target";
const CHOICE_LABEL: Record<Choice, string> = { value: "값", setting: "설정", secret: "비밀", target: "대상" };

function Section({ title, children, part }: { title: string; children: React.ReactNode; part: string }) {
  const [open, setOpen] = useState(true);
  return (
    <section aria-label={title} className={css.section} data-part={part}>
      <button type="button" aria-expanded={open} className={css.sectionHeader} onClick={() => setOpen(!open)}>
        {open ? <ChevronDownIcon /> : <ChevronRightIcon />}
        <span className={css.sectionTitle}>{title}</span>
      </button>
      {open && <div className={css.sectionBody}>{children}</div>}
    </section>
  );
}

function Diagnostics({ list }: { list: readonly Diagnostic[] }) {
  if (list.length === 0) return null;
  return (
    <ul className={css.diagnostics} data-part="field-diagnostics">
      {list.map((d, i) => (
        <li key={i} className={d.severity === "error" ? css.diagError : css.diagWarn} title={d.code}>
          {d.message}
        </li>
      ))}
    </ul>
  );
}

interface FieldProps {
  spec: FieldSpec;
  field: NodeField;
  value: unknown;
  node: string;
  diagnostics: readonly Diagnostic[];
  edit(fn: (v: GraphValue) => GraphValue): void;
  ctx: EditorContext;
  /** 선언에 없는 키 */
  extra?: boolean;
}

/** 핀(또는 config 키) 하나: 이름·타입, 값/설정/비밀/대상 고르기, 입력, 기본값으로 되돌리기, 진단 */
function Field({ spec, field, value, node, diagnostics, edit, ctx: outer, extra }: FieldProps) {
  // 특수 값(연결·대상·설정·비밀·$literal)은 입력 핀 안에서만 해석한다. config는 선언 타입의 보통 값이다 (검수 2)
  const specials = field === "in";
  const ctx: EditorContext = specials ? outer : { ...outer, specials: false };
  const editor = editorFor(spec, { specials });
  const mode = valueModeFor(value, specials);
  const choices: Choice[] = [];
  if (!["target", "secret", "link-only"].includes(editor.kind)) choices.push("value");
  if (editor.allowSetting) choices.push("setting");
  if (editor.allowTarget) choices.push("target");
  if (editor.allowSecret) choices.push("secret");
  if (choices.length === 0) choices.push("value");
  const fromValue: Choice = mode === "setting" ? "setting" : mode === "secret" ? "secret" : mode === "target" ? "target" : "value";
  // 타입에 맞지 않는 특수 값(정수 핀의 `$target` 등)도 그대로 보인다. 검증 오류는 아래 진단으로 나온다
  if (!choices.includes(fromValue) && fromValue !== "value") choices.push(fromValue);
  const current = choices.includes(fromValue) ? fromValue : choices[0];
  const [chosen, setChosen] = useState<Choice | null>(null);
  const shown = chosen ?? current;
  const fixed = mode === "link" || mode === "linked-inside" || mode === "literal";
  const label = spec.name;
  const commit = (v: unknown) => {
    edit((val) => setNodeValue(val, node, field, spec.name, v));
    setChosen(null);
  };
  const disconnectPin = () => edit((val) => disconnect(val, { kind: "data", node, pin: spec.name, path: [] }));

  let body: React.ReactNode;
  if (mode === "link") {
    body = <LinkView value={value} ctx={ctx} onDisconnect={disconnectPin} />;
  } else if (mode === "linked-inside") {
    body = (
      <>
        <div className={`${css.readonly} ${css.mono}`} data-part="linked-inside">
          {formatJson(value)}
        </div>
        <div className={css.row}>
          <span className={css.muted}>안쪽에 연결이 있어요</span>
          <button type="button" className={css.button} disabled={ctx.locked} onClick={disconnectPin}>
            연결 끊기
          </button>
        </div>
      </>
    );
  } else if (mode === "literal") {
    body = <LiteralView value={value} />;
  } else if (shown === "target") {
    const inner = mode === "target" ? own(value, "$target") : "";
    body = (
      <TargetField
        label={label}
        value={typeof inner === "string" ? inner : ""}
        onCommit={(p) => commit({ $target: p })}
        ctx={ctx}
        node={node}
        pin={spec.name}
        title={ctx.titleOf(node)}
      />
    );
  } else if (shown === "setting" || shown === "secret") {
    const tag = shown === "setting" ? "$setting" : "$secret";
    const inner = mode === shown ? own(value, tag) : "";
    body = <KeyInput label={label} tag={tag} value={typeof inner === "string" ? inner : ""} onCommit={(k) => commit({ [tag]: k })} ctx={ctx} />;
  } else if (editor.kind === "link-only") {
    body =
      value === undefined ? (
        <div className={css.muted}>캔버스에서 연결로 받아요</div>
      ) : (
        <JsonInput label={label} value={value} onCommit={commit} ctx={ctx} />
      );
  } else {
    // "값"을 고른 상수 입력. 설정·비밀·대상 값에서 "값"으로 바꾸면 빈 상자에서 새로 넣는다
    const constant = mode === "constant" ? value : undefined;
    body = <ConstantEditor editor={editor} spec={spec} label={label} value={constant} onCommit={commit} ctx={ctx} />;
  }

  return (
    <div className={css.field} data-part="field" data-field={field} data-pin={spec.name} data-mode={fixed ? mode : shown}>
      <div className={css.fieldHead}>
        <span className={css.fieldName} title={spec.description}>
          {spec.name}
          {spec.required && !extra && (
            <span className={css.required} aria-label="필수">
              *
            </span>
          )}
        </span>
        <span className={css.fieldType}>{extra ? "선언에 없음" : spec.type}</span>
        <span className={css.grow} />
        {!fixed && choices.length > 1 && (
          <select
            aria-label={`${label} 값 종류`}
            className={css.choice}
            value={shown}
            disabled={ctx.locked}
            onChange={(e) => setChosen(e.target.value as Choice)}
          >
            {choices.map((c) => (
              <option key={c} value={c}>
                {CHOICE_LABEL[c]}
              </option>
            ))}
          </select>
        )}
        {value !== undefined && (
          <button
            type="button"
            aria-label={`${label} 지우기`}
            title={spec.default !== undefined ? "기본값으로" : "지우기"}
            className={css.iconButton}
            disabled={ctx.locked}
            onClick={() => {
              setChosen(null);
              edit((val) => clearNodeValue(val, node, field, spec.name));
            }}
          >
            ×
          </button>
        )}
      </div>
      {body}
      <Diagnostics list={diagnostics} />
    </div>
  );
}

function NodeFields({ path, view, ctx }: { path: string; view: NodeInspector; ctx: EditorContext }) {
  const { node } = view;
  const edit = (fn: (v: GraphValue) => GraphValue) => void applyEdit(path, fn);
  const field = (spec: FieldSpec, f: NodeField, extra = false) => (
    <Field
      key={`${f}:${spec.name}`}
      spec={spec}
      field={f}
      value={own(f === "in" ? node.in : node.config, spec.name)}
      node={node.id}
      diagnostics={view.diagnostics[f].get(spec.name) ?? []}
      edit={edit}
      ctx={ctx}
      extra={extra}
    />
  );
  const extraSpec = (name: string): FieldSpec => ({ name, type: "any", required: false });
  const rawTitle = own(node.raw, "title");
  return (
    <>
      <Section title="노드" part="inspector-node">
        <div className={css.field} data-part="field" data-pin="title">
          <div className={css.fieldHead}>
            <span className={css.fieldName}>제목</span>
          </div>
          <TitleInput
            value={typeof rawTitle === "string" ? rawTitle : ""}
            placeholder={view.defaultTitle}
            ctx={ctx}
            onCommit={(t) => edit((v) => setNodeTitle(v, node.id, t))}
          />
        </div>
        <dl className={css.meta}>
          <dt>종류</dt>
          <dd className={css.mono} data-part="node-type">
            {node.type === "" ? "(없음)" : node.type}
            {node.version !== null ? ` · v${node.version}` : ""}
          </dd>
          <dt>ID</dt>
          <dd className={css.mono} data-part="node-id">
            {node.id}
          </dd>
        </dl>
        {view.info?.description != null && <p className={css.description}>{view.info.description}</p>}
        {view.unknown && (
          <p className={css.unknownNote} data-part="unknown-note">
            모르는 노드예요 (설치되지 않은 플러그인이거나 다른 판). 입력·설정은 JSON으로 고치고, 고친 키만 바뀌어요.
          </p>
        )}
        <Diagnostics list={view.diagnostics.node} />
      </Section>
      {view.unknown ? (
        <>
          <Section title="입력" part="inspector-in">
            <ObjectBox label="입력 JSON" field="in" view={view} edit={edit} ctx={ctx} />
          </Section>
          <Section title="설정" part="inspector-config">
            <ObjectBox label="설정 JSON" field="config" view={view} edit={edit} ctx={ctx} />
          </Section>
        </>
      ) : (
        <>
          <Section title="입력" part="inspector-in">
            {view.inputs.length === 0 && view.extraInputs.length === 0 && <div className={css.muted}>입력이 없어요</div>}
            {view.inputs.map((p) => field(p, "in"))}
            {view.extraInputs.map((k) => field(extraSpec(k), "in", true))}
          </Section>
          {(view.config.length > 0 || view.extraConfig.length > 0) && (
            <Section title="설정" part="inspector-config">
              {view.config.map((p) => field(p, "config"))}
              {view.extraConfig.map((k) => field(extraSpec(k), "config", true))}
            </Section>
          )}
        </>
      )}
    </>
  );
}

function TitleInput({
  value,
  placeholder,
  onCommit,
  ctx,
}: {
  value: string;
  placeholder: string;
  onCommit(t: string): void;
  ctx: EditorContext;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const keys = useEditKeys();
  const commit = () => {
    if (draft !== null && draft !== value) onCommit(draft.trim());
    setDraft(null);
  };
  return (
    <label className={css.box}>
      <input
        aria-label="제목"
        value={draft ?? value}
        placeholder={placeholder}
        disabled={ctx.locked}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={keys.onBlur(commit)}
        onKeyDown={keys.onKeyDown(commit, () => setDraft(null))}
      />
    </label>
  );
}

/** 모르는 노드의 in·config JSON 상자: 바뀐 키만 바꾼다 */
function ObjectBox({
  label,
  field,
  view,
  edit,
  ctx,
}: {
  label: string;
  field: NodeField;
  view: NodeInspector;
  edit(fn: (v: GraphValue) => GraphValue): void;
  ctx: EditorContext;
}) {
  const current = own(view.node.raw, field);
  const diags = [...view.diagnostics[field].values()].flat();
  return (
    <div className={css.field} data-part="field" data-field={field} data-pin={`${field}-json`}>
      <JsonInput
        label={label}
        value={current === undefined ? {} : current}
        rows={Math.min(14, Math.max(3, formatJson(current ?? {}, 2).split("\n").length))}
        parse={parseJsonObject}
        onCommit={(obj) => edit((v) => replaceNodeObject(v, view.node.id, field, obj as Record<string, unknown>))}
        ctx={ctx}
      />
      <div className={css.hint}>Ctrl+Enter 또는 칸을 떠나면 반영해요</div>
      <Diagnostics list={diags} />
    </div>
  );
}

function Body({ path }: { path: string }) {
  const doc = useDocuments((s) => s.docs.get(path));
  const types = useRegistry((s) => s.types);
  const locked = useEditsLocked();
  if (doc === undefined || doc.status !== "ready" || doc.value === null) {
    return <div className={css.empty}>그래프를 여는 중이에요</div>;
  }
  if (doc.view.selection.length > 1) {
    return <div className={css.empty}>노드 {doc.view.selection.length}개를 골랐어요. 하나만 고르면 속성을 고칠 수 있어요</div>;
  }
  const nodes = graphNodes(doc.value);
  const node = nodes.find((n) => n.id === doc.view.selected);
  if (node === undefined) return <div className={css.empty}>노드를 고르면 속성이 보여요</div>;
  const titles = new Map(nodes.map((n) => [n.id, n.title ?? types.get(n.type)?.title ?? n.id]));
  // 실행 스냅샷 그래프는 읽기 전용이다 (M3 2.10)
  const ctx: EditorContext = { locked: locked || doc.readOnly, titleOf: (id) => titles.get(id) ?? id, graph: path };
  const view = inspectNode(node, doc.shapes, types, doc.diagnostics, path);
  return (
    <div className={css.body} data-part="inspector-body" data-node={node.id}>
      <NodeFields key={`${path}:${node.id}`} path={path} view={view} ctx={ctx} />
    </div>
  );
}

/** 지금 탭이 그래프면 그 경로 */
function useActiveGraph(): string | null {
  return useTabs((s) => (s.tabs.find((t) => t.path === s.active)?.kind === "graph" ? s.active : null));
}

export function Inspector() {
  const path = useActiveGraph();
  const open = useUi((s) => s.inspectorOpen);
  if (path === null) return null;
  if (!open) {
    return (
      <aside aria-label="속성" className={`${css.inspector} ${css.collapsed}`} data-part="inspector" data-open="false">
        <button
          type="button"
          aria-label="속성 패널 펼치기"
          className={css.collapsedButton}
          onClick={() => useUi.setState({ inspectorOpen: true })}
        >
          <span className={css.vertical}>속성</span>
        </button>
      </aside>
    );
  }
  return (
    <aside aria-label="속성" className={css.inspector} data-part="inspector" data-open="true">
      <div className={css.header}>
        <span>속성</span>
        <button
          type="button"
          aria-label="속성 패널 접기"
          className={css.iconButton}
          onClick={() => useUi.setState({ inspectorOpen: false })}
        >
          »
        </button>
      </div>
      <Body path={path} />
    </aside>
  );
}
