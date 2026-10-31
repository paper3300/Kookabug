// 사이드바 탐색기 (M2 계획 2.11): workspace.tree, 배지, workspace.changed로 다시 읽기
import { useMemo } from "react";
import { openTab, useTabs } from "../store/tabs";
import { toggleExpanded, useUi } from "../store/ui";
import { useWorkspace } from "../store/workspace";
import { badgeOf, buildTree, defaultExpanded, glyphOf, isOpenable, visibleRows, type Tone, type TreeNode } from "./tree";
import css from "./explorer.module.css";

const TONE: Record<Tone, string> = {
  test: css.toneTest,
  target: css.toneTarget,
  json: css.toneJson,
  md: css.toneMd,
  muted: css.toneMuted,
  error: css.toneError,
};

export function Explorer() {
  const entries = useWorkspace((s) => s.entries);
  const loaded = useWorkspace((s) => s.treeLoaded);
  const stored = useUi((s) => s.expanded);
  const selected = useUi((s) => s.selected);
  const active = useTabs((s) => s.active);
  const nodes = useMemo(() => buildTree(entries), [entries]);
  const expanded = stored ?? defaultExpanded(nodes);
  const rows = useMemo(() => visibleRows(nodes, expanded), [nodes, expanded]);

  if (!loaded) return <div className={css.empty}>불러오는 중…</div>;
  if (rows.length === 0) return <div className={css.empty}>빈 워크스페이스예요</div>;

  const activate = (node: TreeNode) => {
    useUi.setState({ selected: node.path });
    if (node.type === "dir") {
      if (!node.nameOnly) toggleExpanded(node.path, expanded);
      return;
    }
    if (isOpenable({ type: "file", kind: node.kind ?? undefined })) {
      openTab({ path: node.path, kind: node.kind as "graph" | "target", graphKind: node.graphKind });
    }
  };

  return (
    <div role="tree" aria-label="워크스페이스 파일" className={css.tree}>
      {rows.map(({ node, depth, expanded: open }) => {
        const glyph = glyphOf(node);
        const badge = badgeOf(node, depth === 0);
        const isSelected = node.path === (selected ?? active);
        const classes = [css.row];
        if (isSelected) classes.push(css.selected);
        if (node.problem) classes.push(css.problem);
        if (node.gitIgnored && node.type === "dir") classes.push(css.ignored);
        return (
          <div
            key={node.path}
            role="treeitem"
            aria-level={depth + 1}
            aria-selected={isSelected}
            aria-expanded={node.type === "dir" && !node.nameOnly ? open : undefined}
            data-path={node.path}
            tabIndex={isSelected ? 0 : -1}
            className={classes.join(" ")}
            style={{ paddingLeft: 8 + depth * 16 }}
            title={node.problem ?? node.path}
            onClick={() => activate(node)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                activate(node);
              }
            }}
          >
            <span className={css.chevron}>{node.type === "dir" && !node.nameOnly ? (open ? "⌄" : "›") : ""}</span>
            <span className={`${css.glyph} ${glyph ? TONE[glyph.tone] : ""}`}>{glyph?.glyph ?? ""}</span>
            <span className={css.name}>{node.name}</span>
            {badge && (
              <span className={`${css.badge} ${TONE[badge.tone]}`} title={badge.title}>
                {badge.text}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}
