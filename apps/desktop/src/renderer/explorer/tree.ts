// 탐색기 트리 (M2 계획 2.11 "사이드바 탐색기"). workspace.tree의 평평한 항목 목록 → 폴더 트리·보이는 줄.
// 순수 함수라 vitest로 검사한다
import type { daemonRpc } from "@kookabug/schema";

export type TreeEntry = daemonRpc.TreeEntry;

export interface TreeNode {
  path: string;
  name: string;
  type: "dir" | "file";
  kind: TreeEntry["kind"] | null;
  graphKind: TreeEntry["graph_kind"] | null;
  problem: string | null;
  gitIgnored: boolean;
  nameOnly: boolean;
  children: TreeNode[];
}

export interface TreeRow {
  node: TreeNode;
  depth: number;
  expanded: boolean;
}

/** 워크스페이스 최상위 순서 (시안 Main 탐색기): 폴더 → 설정 파일 */
const TOP_ORDER = ["tests", "subgraphs", "targets", "screens", "runs", "kookabug.json", "kookabug.lock", "AGENTS.md"];
/** 탐색기에 보이지 않는 최상위 이름 (`.kookabug/`는 이 PC 전용 비공개 폴더) */
const HIDDEN_TOP = new Set([".kookabug"]);

function compareNodes(top: boolean) {
  return (a: TreeNode, b: TreeNode): number => {
    if (top) {
      const ia = TOP_ORDER.indexOf(a.name);
      const ib = TOP_ORDER.indexOf(b.name);
      if (ia >= 0 || ib >= 0) return (ia < 0 ? TOP_ORDER.length : ia) - (ib < 0 ? TOP_ORDER.length : ib);
    }
    if (a.type !== b.type) return a.type === "dir" ? -1 : 1;
    const la = a.name.toLowerCase();
    const lb = b.name.toLowerCase();
    return la < lb ? -1 : la > lb ? 1 : 0;
  };
}

export function buildTree(entries: readonly TreeEntry[]): TreeNode[] {
  const roots: TreeNode[] = [];
  const dirs = new Map<string, TreeNode>();
  const ensureDir = (dirPath: string): TreeNode[] => {
    if (dirPath === "") return roots;
    const found = dirs.get(dirPath);
    if (found) return found.children;
    const slash = dirPath.lastIndexOf("/");
    const node: TreeNode = {
      path: dirPath,
      name: dirPath.slice(slash + 1),
      type: "dir",
      kind: null,
      graphKind: null,
      problem: null,
      gitIgnored: false,
      nameOnly: false,
      children: [],
    };
    dirs.set(dirPath, node);
    ensureDir(slash < 0 ? "" : dirPath.slice(0, slash)).push(node);
    return node.children;
  };
  for (const e of entries) {
    const top = e.path.split("/", 1)[0];
    if (HIDDEN_TOP.has(top)) continue;
    const slash = e.path.lastIndexOf("/");
    const parent = slash < 0 ? "" : e.path.slice(0, slash);
    if (e.type === "dir") {
      ensureDir(e.path);
      const node = dirs.get(e.path)!;
      node.gitIgnored = e.git_ignored ?? false;
      node.nameOnly = e.name_only ?? false;
      continue;
    }
    ensureDir(parent).push({
      path: e.path,
      name: e.path.slice(slash + 1),
      type: "file",
      kind: e.kind ?? null,
      graphKind: e.graph_kind ?? null,
      problem: e.problem ?? null,
      gitIgnored: e.git_ignored ?? false,
      nameOnly: false,
      children: [],
    });
  }
  const sort = (list: TreeNode[], top: boolean) => {
    list.sort(compareNodes(top));
    for (const n of list) sort(n.children, false);
  };
  sort(roots, true);
  return roots;
}

/** 펼친 폴더를 따라 보이는 줄 */
export function visibleRows(nodes: readonly TreeNode[], expanded: ReadonlySet<string>, depth = 0): TreeRow[] {
  const rows: TreeRow[] = [];
  for (const node of nodes) {
    const open = node.type === "dir" && expanded.has(node.path);
    rows.push({ node, depth, expanded: open });
    if (open) rows.push(...visibleRows(node.children, expanded, depth + 1));
  }
  return rows;
}

export type Tone = "test" | "target" | "json" | "md" | "muted" | "error";

/** 파일 앞 글자 표시 (시안: 테스트 T, 설정 {}, 문서 MD) */
export function glyphOf(node: TreeNode): { glyph: string; tone: Tone } | null {
  if (node.type === "dir") return null;
  switch (node.kind) {
    case "graph":
      return { glyph: node.graphKind === "subgraph" ? "S" : "T", tone: node.problem ? "error" : "test" };
    case "target":
      return { glyph: "◎", tone: node.problem ? "error" : "target" };
    case "screen":
      return { glyph: "▣", tone: "muted" };
    case "workspace":
    case "lock":
      return { glyph: "{}", tone: "json" };
    case "agents":
      return { glyph: "MD", tone: "md" };
    default:
      return null;
  }
}

function countKind(node: TreeNode, kind: TreeEntry["kind"]): number {
  let n = 0;
  for (const c of node.children) n += c.type === "dir" ? countKind(c, kind) : c.kind === kind ? 1 : 0;
  return n;
}

/** 줄 오른쪽 배지 (시안: runs "Git 제외", targets 개수, 읽을 수 없는 그래프) */
export function badgeOf(node: TreeNode, top: boolean): { text: string; tone: Tone; title?: string } | null {
  if (node.problem) return { text: "오류", tone: "error", title: node.problem };
  if (node.type === "dir" && node.gitIgnored) return { text: "Git 제외", tone: "muted" };
  if (node.type === "dir" && top && node.name === "targets") {
    const n = countKind(node, "target");
    return n > 0 ? { text: String(n), tone: "muted" } : null;
  }
  return null;
}

/** 에디터 탭으로 여는 파일 (그래프·target) */
export function isOpenable(entry: Pick<TreeEntry, "type" | "kind">): boolean {
  return entry.type === "file" && (entry.kind === "graph" || entry.kind === "target");
}

/** 파일 이름에서 종류 접미사를 뺀 표시 이름 */
export function displayName(path: string): string {
  const name = path.slice(path.lastIndexOf("/") + 1);
  return name.replace(/\.(graph|target|screen)\.json$/, "");
}

export interface QuickOpenItem {
  path: string;
  name: string;
  kind: "graph" | "target";
  graphKind: TreeEntry["graph_kind"] | null;
}

/** Ctrl+P 파일 빠른 열기 목록: 워크스페이스 그래프·target (2.11) */
export function quickOpenItems(entries: readonly TreeEntry[]): QuickOpenItem[] {
  return entries
    .filter((e) => isOpenable(e) && !HIDDEN_TOP.has(e.path.split("/", 1)[0]))
    .map((e) => ({
      path: e.path,
      name: displayName(e.path),
      kind: e.kind as "graph" | "target",
      graphKind: e.graph_kind ?? null,
    }))
    .sort((a, b) => (a.path < b.path ? -1 : a.path > b.path ? 1 : 0));
}

/** 부분 일치 (대소문자 무시, 한글 그대로). 이름에 맞는 것을 경로에만 맞는 것보다 앞에 */
export function filterQuickOpen(items: readonly QuickOpenItem[], query: string): QuickOpenItem[] {
  const q = query.trim().toLowerCase();
  if (q === "") return items.slice();
  const byName: QuickOpenItem[] = [];
  const byPath: QuickOpenItem[] = [];
  for (const item of items) {
    if (item.name.toLowerCase().includes(q)) byName.push(item);
    else if (item.path.toLowerCase().includes(q)) byPath.push(item);
  }
  return [...byName, ...byPath];
}

/** 처음 열 때 펼칠 폴더: 최상위 tests (시안처럼 테스트가 보이게) */
export function defaultExpanded(nodes: readonly TreeNode[]): Set<string> {
  return new Set(nodes.filter((n) => n.type === "dir" && n.name === "tests").map((n) => n.path));
}
