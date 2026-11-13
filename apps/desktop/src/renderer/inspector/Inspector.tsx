// 속성 편집기 (M2 계획 2.11, T10, U1): 오른쪽 패널(에이전트 패널 자리, 폭 320px, 접기 가능). 사이드바와 같은 섹션
// 머리·입력 상자 모양이다. 고른 노드(문서 보기 상태의 주 노드)의 제목·입력 핀·config를 고친다.
// - 고치기는 문서 표의 applyEdit 하나로만 한다 (편집 잠금·실행 취소 기록·검증 요청이 함께 된다, T9 인계)
// - 핀 모양은 daemon 결과다. config 배열(동적 출구)을 고치면 검증 응답으로 출구 핀이 바뀐다. 이름이 바뀌어 끊긴
//   next는 그대로 두고 문제 패널에 나오게 한다
// - 모르는 노드는 in·config를 JSON 상자로 보여 주고, 고치면 바뀐 키만 바꾼다
// - 입력 효과 노드는 "실행 전" 묶음(입력 전 게임 창 앞으로: 그래프 기본값·켬·끔), 노드를 고르지 않았으면 그래프 설정
//   (그 기본값 토글, UX4)
import { useState } from "react";
import {
  clearNodeValue,
  disconnect,
  graphFocus,
  nodeFocus,
  replaceNodeObject,
  setGraphFocus,
  setNodeFocus,
  setNodeTitle,
  setNodeValue,
  type NodeField,
} from "../graph/commands";
import { graphNodes, own, type Diagnostic, type GraphValue } from "../graph/model";
import { openSubgraph } from "../graph/openSubgraph";
import { GRAPH_CALL_TYPE } from "../graph/subgraphPlan";
import { useAgent } from "../agent/agentStore";
import { useEditsLocked } from "../store/dialog";
import { applyEdit, useDocuments } from "../store/documents";
import { useRegistry } from "../store/registry";
import { openPluginTab, useTabs } from "../store/tabs";
import { ENV_STATUS_TEXT, pluginTitle } from "../plugins/model";
import { usePlugins } from "../plugins/pluginStore";
import { NodeResult } from "../run/NodeResult";
import { useRun } from "../run/runStore";
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
import { PluginWidget } from "./PluginWidget";
import { widgetBlock } from "./widgetSession";

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
  /** 판단 노드의 에이전트: 사용자 설정 목록에서 고른다 (M5 U11) */
  agentPicker?: boolean;
  /** 그 노드 타입의 플러그인 ID (위젯은 자기 플러그인 것만) */
  nodePlugin?: string | null;
}

const CLI_JUDGE_TYPE = "core.agent.cli_judge";

/** `core.agent.cli_judge`의 agent 칸: 사용자 설정(agents.get) 목록. 빈 값 = 기본 에이전트 */
function AgentPicker({ label, value, onCommit, ctx }: { label: string; value: unknown; onCommit(v: string): void; ctx: EditorContext }) {
  const agents = useAgent((s) => s.agents);
  const loaded = useAgent((s) => s.agentsLoaded);
  const defaultAgent = useAgent((s) => s.defaultAgent);
  const current = typeof value === "string" ? value : "";
  const known = current === "" || agents.some((a) => a.id === current);
  return (
    <div className={css.box}>
    <select
      aria-label={label}
      data-part="agent-picker"
      value={current}
      disabled={ctx.locked || !loaded}
      onChange={(e) => onCommit(e.target.value)}
    >
      <option value="">기본 에이전트{defaultAgent !== null ? ` (${defaultAgent})` : ""}</option>
      {agents.map((a) => (
        <option key={a.id} value={a.id}>
          {a.name} ({a.id})
        </option>
      ))}
      {!known && <option value={current}>{current} (이 PC 설정에 없음)</option>}
    </select>
    </div>
  );
}

/** 핀(또는 config 키) 하나: 이름·타입, 값/설정/비밀/대상 고르기, 입력, 기본값으로 되돌리기, 진단 */
function Field({ spec, field, value, node, diagnostics, edit, ctx: outer, extra, agentPicker, nodePlugin }: FieldProps) {
  const widgetOwner = spec.widget?.split(".", 1)[0];
  const widgetPlugin = usePlugins((s) =>
    widgetOwner === undefined ? undefined : s.list?.plugins.find((p) => p.id === widgetOwner),
  );
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
  } else if (agentPicker === true) {
    body = <AgentPicker label={label} value={value} onCommit={commit} ctx={ctx} />;
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
    const plain = <ConstantEditor editor={editor} spec={spec} label={label} value={constant} onCommit={commit} ctx={ctx} />;
    // 플러그인 위젯 (M6 3.10): 잠금에 있고 환경이 준비된 그 노드 플러그인의 위젯만. 비밀값 항목에는 절대 쓰지 않는다
    const host = widgetPlugin !== undefined && widgetBlock(spec, field, value, widgetPlugin, nodePlugin ?? null) === null
      ? widgetPlugin.ui
      : undefined;
    body =
      host !== undefined && spec.widget !== undefined ? (
        <PluginWidget
          key={`${host.host}:${spec.widget}`}
          host={host.host}
          widget={spec.widget}
          spec={spec}
          label={label}
          value={constant}
          readOnly={ctx.locked || ctx.running === true}
          onCommit={commit}
          fallback={plain}
        />
      ) : (
        plain
      );
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

function NodeFields({ path, view, ctx, graph }: { path: string; view: NodeInspector; ctx: EditorContext; graph: GraphValue }) {
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
      agentPicker={f === "config" && spec.name === "agent" && node.type === CLI_JUDGE_TYPE}
      nodePlugin={view.info?.plugin ?? null}
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
          <PluginBadge plugin={view.info?.plugin ?? null} />
        </dl>
        {view.info?.description != null && <p className={css.description}>{view.info.description}</p>}
        {node.type === GRAPH_CALL_TYPE && <OpenSubgraphButton path={path} node={node.id} config={node.config} />}
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
      {view.info?.effects.includes("input") === true && (
        <Section title="실행 전" part="inspector-before">
          <FocusChoice graph={graph} node={node.id} ctx={ctx} edit={edit} />
        </Section>
      )}
    </>
  );
}

const FOCUS_CHOICES = [
  { value: "inherit", label: "그래프 기본값 따름" },
  { value: "on", label: "켬" },
  { value: "off", label: "끔" },
] as const;

/** 입력 노드 "실행 전": 입력 전 게임 창 앞으로 (UX4). 그래프 기본값 따름·켬·끔 */
function FocusChoice({
  graph,
  node,
  ctx,
  edit,
}: {
  graph: GraphValue;
  node: string;
  ctx: EditorContext;
  edit(fn: (v: GraphValue) => GraphValue): void;
}) {
  const current = nodeFocus(graph, node);
  const value = current === null ? "inherit" : current ? "on" : "off";
  const fallback = graphFocus(graph) ? "켜짐" : "꺼짐";
  return (
    <div className={css.field} data-part="field" data-pin="focus_before_input">
      <div className={css.fieldHead}>
        <span className={css.fieldName}>입력 전 게임 창 앞으로</span>
      </div>
      <label className={css.box}>
        <select
          aria-label="입력 전 게임 창 앞으로"
          data-part="focus-choice"
          value={value}
          disabled={ctx.locked}
          onChange={(e) => {
            const v = e.target.value;
            edit((g) => setNodeFocus(g, node, v === "inherit" ? null : v === "on"));
          }}
        >
          {FOCUS_CHOICES.map((c) => (
            <option key={c.value} value={c.value}>
              {c.value === "inherit" ? `${c.label} (${fallback})` : c.label}
            </option>
          ))}
        </select>
      </label>
      <div className={css.hint}>입력하기 직전에 대상 창을 앞으로 가져와요. 끄면 앞에 없을 때 오류예요</div>
    </div>
  );
}

/** 노드를 고르지 않았을 때: 그래프 설정 (UX4 — 입력 전 게임 창 앞으로 기본값) */
function GraphSettings({ path, graph, ctx }: { path: string; graph: GraphValue; ctx: EditorContext }) {
  const on = graphFocus(graph);
  return (
    <Section title="그래프 설정" part="inspector-graph">
      <label className={css.check} data-part="graph-focus">
        <input
          type="checkbox"
          checked={on}
          disabled={ctx.locked}
          onChange={(e) => void applyEdit(path, (g) => setGraphFocus(g, e.target.checked))}
        />
        입력 전 게임 창 앞으로 (기본값)
      </label>
      <div className={css.hint}>입력 노드마다 "실행 전"에서 따로 켜거나 끌 수 있어요</div>
    </Section>
  );
}

/** 설치 플러그인(잠금에 있는 것)의 노드면 머리에 플러그인 배지 (M6 B5). 누르면 그 플러그인 상세 탭 */
function PluginBadge({ plugin }: { plugin: string | null }) {
  const entry = usePlugins((s) => (plugin === null ? undefined : s.list?.plugins.find((p) => p.id === plugin)));
  if (entry === undefined) return null;
  const title = pluginTitle(entry);
  return (
    <>
      <dt>플러그인</dt>
      <dd>
        <button
          type="button"
          className={css.pluginBadge}
          data-part="node-plugin"
          data-status={entry.env_status}
          title={`${entry.id} · ${ENV_STATUS_TEXT[entry.env_status]}`}
          onClick={() => openPluginTab(entry.id, title)}
        >
          {title} · {entry.version}
        </button>
      </dd>
    </>
  );
}

/** 서브그래프 호출 노드: 캔버스 더블클릭과 같은 "서브그래프 열기" (다듬기 P1-B). 읽기 전용·실행 중에도 된다 */
function OpenSubgraphButton({ path, node, config }: { path: string; node: string; config: Record<string, unknown> }) {
  const graph = own(config, "graph");
  const target = typeof graph === "string" ? graph : "";
  return (
    <div className={css.row}>
      <button
        type="button"
        className={css.button}
        data-part="open-subgraph"
        data-node={node}
        title={target === "" ? "config.graph가 비어 있어요" : target}
        onClick={() => void openSubgraph(path, target)}
      >
        서브그래프 열기
      </button>
    </div>
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
  const running = useRun((s) => s.current?.phase === "running");
  if (doc === undefined || doc.status !== "ready" || doc.value === null) {
    return <div className={css.empty}>그래프를 여는 중이에요</div>;
  }
  if (doc.view.selection.length > 1) {
    return <div className={css.empty}>노드 {doc.view.selection.length}개를 골랐어요. 하나만 고르면 속성을 고칠 수 있어요</div>;
  }
  const nodes = graphNodes(doc.value);
  const node = nodes.find((n) => n.id === doc.view.selected);
  const titles = new Map(nodes.map((n) => [n.id, n.title ?? types.get(n.type)?.title ?? n.id]));
  // 실행 스냅샷 그래프는 읽기 전용이다 (M3 2.10)
  const ctx: EditorContext = { locked: locked || doc.readOnly, titleOf: (id) => titles.get(id) ?? id, graph: path, running };
  if (node === undefined) {
    return (
      <div className={css.body} data-part="inspector-body">
        <div className={css.empty}>노드를 고르면 속성이 보여요</div>
        <GraphSettings path={path} graph={doc.value} ctx={ctx} />
      </div>
    );
  }
  const view = inspectNode(node, doc.shapes, types, doc.diagnostics, path);
  return (
    <div className={css.body} data-part="inspector-body" data-node={node.id}>
      <NodeFields key={`${path}:${node.id}`} path={path} view={view} ctx={ctx} graph={doc.value} />
      {/* 하단 패널 "노드 결과"를 옮겼다 (UX6): 고른 노드의 마지막 step.end */}
      <Section title="마지막 실행 결과" part="node-last-result">
        <NodeResult />
      </Section>
    </div>
  );
}

/** 지금 탭이 그래프면 그 경로 */
export function useActiveGraph(): string | null {
  return useTabs((s) => (s.tabs.find((t) => t.path === s.active)?.kind === "graph" ? s.active : null));
}

/** 오른쪽 패널 "속성" 탭 내용 (M5 B5: 패널 틀은 app/RightPanel.tsx) */
export function InspectorContent() {
  const path = useActiveGraph();
  if (path === null) return <div className={css.empty}>그래프를 열고 노드를 고르면 속성이 보여요</div>;
  return <Body path={path} />;
}
