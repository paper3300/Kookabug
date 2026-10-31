// 문제 패널 (M2 계획 2.8 "문제: 검증 진단", T8): 열린 그래프 문서의 진단. 지금 탭이 먼저, 그 안에서는 오류
// 먼저. 같은 진단이 여러 문서에 나오면(서브그래프 진단) 한 번만 쓴다. 누르면 그 노드를 고르고 옮겨 간다
import { useMemo } from "react";
import type { Diagnostic } from "../graph/model";
import { graphNodes } from "../graph/model";
import { focusNode, requestFocus, useDocuments, type GraphDoc } from "../store/documents";
import { activateTab, openTab, useTabs } from "../store/tabs";
import { useWorkspace } from "../store/workspace";
import { problemNode, sortProblems } from "./locate";
import css from "./problems.module.css";

export interface ProblemItem {
  key: string;
  diag: Diagnostic;
  /** 진단이 나온 문서 */
  doc: string;
  /** 진단의 파일 (없으면 문서) */
  file: string;
  /** 이 문서에서 고를 노드 */
  node: string | null;
  nodeTitle: string | null;
}

function itemsOf(doc: GraphDoc): ProblemItem[] {
  if (doc.status !== "ready" || doc.value === null) return [];
  const nodes = graphNodes(doc.value);
  const ids = new Set(nodes.map((n) => n.id));
  const titles = new Map(nodes.map((n) => [n.id, n.title]));
  return doc.diagnostics.map((diag) => {
    const node = problemNode(diag, doc.path, ids);
    return {
      key: JSON.stringify([diag.file ?? doc.path, diag.pointer ?? null, diag.code, diag.node ?? null, diag.message]),
      diag,
      doc: doc.path,
      file: diag.file ?? doc.path,
      node,
      nodeTitle: node === null ? null : (titles.get(node) ?? null),
    };
  });
}

export function useProblems(): ProblemItem[] {
  const docs = useDocuments((s) => s.docs);
  const tabs = useTabs((s) => s.tabs);
  const active = useTabs((s) => s.active);
  return useMemo(() => {
    const order = tabs.map((t) => t.path).filter((p) => docs.has(p));
    order.sort((a, b) => Number(b === active) - Number(a === active));
    const seen = new Set<string>();
    const out: ProblemItem[] = [];
    for (const path of order) {
      for (const item of sortProblems(itemsOf(docs.get(path)!))) {
        if (seen.has(item.key)) continue;
        seen.add(item.key);
        out.push(item);
      }
    }
    return out;
  }, [docs, tabs, active]);
}

function go(item: ProblemItem): void {
  if (item.node !== null) {
    activateTab(item.doc);
    focusNode(item.doc, item.node);
  } else if (item.file !== item.doc && item.file.endsWith(".graph.json")) {
    // 다른 그래프 파일(서브그래프)의 진단: 그 파일을 탭으로 열고, 준비되면 진단의 노드로 옮겨 간다
    const entry = useWorkspace.getState().entries.find((e) => e.path === item.file);
    openTab({ path: item.file, kind: "graph", graphKind: entry?.graph_kind ?? null });
    requestFocus(item.file, { node: item.diag.node ?? null, pointer: item.diag.pointer ?? null });
  } else {
    activateTab(item.doc);
  }
}

export function Problems() {
  const items = useProblems();
  if (items.length === 0) return <div className={css.empty}>문제가 없어요</div>;
  return (
    <ul className={css.list} aria-label="문제 목록">
      {items.map((item) => (
        <li key={`${item.doc}:${item.key}`}>
          <button
            type="button"
            className={css.item}
            data-severity={item.diag.severity}
            data-node={item.node ?? ""}
            data-code={item.diag.code}
            onClick={() => go(item)}
          >
            <span className={css.icon} aria-label={item.diag.severity === "error" ? "오류" : "경고"}>
              {item.diag.severity === "error" ? "✕" : "⚠"}
            </span>
            <span className={css.message}>{item.diag.message}</span>
            <span className={css.where}>
              {item.file}
              {item.node !== null && ` · ${item.nodeTitle ?? item.node}`}
              {` · ${item.diag.code}`}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}
