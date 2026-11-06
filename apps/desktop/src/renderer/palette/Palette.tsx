// 사이드바 "노드" 섹션의 팔레트 (시안 Main): 검색, 분류 묶음(점 색·펼치기), 노드 줄. 노드 줄을 캔버스로 끌어
// 놓으면 그 자리에 노드를 더한다. Enter·두 번 누르기는 열린 캔버스 가운데에 더한다
import { useMemo, useState } from "react";
import { canvasActions } from "../graph/canvasActions";
import { useRegistry } from "../store/registry";
import { useTabs } from "../store/tabs";
import { dotColor, isNondeterministic, NONDETERMINISTIC_BADGE } from "./categories";
import { DEFAULT_OPEN, groupKey, PALETTE_MIME, paletteGroups, type PaletteItem } from "./groups";
import css from "./palette.module.css";
import shell from "../app/shell.module.css";

function addToActive(item: PaletteItem): void {
  const { active, tabs } = useTabs.getState();
  if (tabs.find((t) => t.path === active)?.kind !== "graph") return;
  canvasActions(active)?.addAtCenter(item.info);
}

export function Palette() {
  const types = useRegistry((s) => s.types);
  const loaded = useRegistry((s) => s.loaded);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<ReadonlySet<string>>(() => new Set(DEFAULT_OPEN));
  const groups = useMemo(() => paletteGroups(types, query), [types, query]);
  const searching = query.trim() !== "";
  const toggle = (key: string) =>
    setOpen((s) => {
      const next = new Set(s);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  return (
    <>
      <div className={shell.paletteSearch}>
        <label className={shell.inputBox}>
          <input
            type="search"
            placeholder="노드 검색"
            aria-label="노드 검색"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
      </div>
      <div role="tree" aria-label="노드 팔레트" className={css.list} data-part="palette">
        {loaded && groups.length === 0 && <div className={css.empty}>{searching ? "맞는 노드가 없어요" : "노드가 없어요"}</div>}
        {groups.map((g) => {
          const key = groupKey(g);
          const expanded = searching || open.has(key);
          const src = g.src ?? g.items[0]?.src ?? "";
          return (
            <div key={key} role="group" aria-label={g.group} data-group={key}>
              <div
                role="treeitem"
                aria-level={1}
                aria-expanded={expanded}
                tabIndex={0}
                className={css.groupRow}
                onClick={() => !searching && toggle(key)}
                onKeyDown={(e) => {
                  if ((e.key === "Enter" || e.key === " ") && !searching) {
                    e.preventDefault();
                    toggle(key);
                  }
                }}
              >
                <span className={css.chevron}>{expanded ? "⌄" : "›"}</span>
                <span className={css.dot} style={{ background: dotColor(g.dot) }} />
                <span className={css.name}>{g.group}</span>
                <span className={css.src}>{src}</span>
              </div>
              {expanded &&
                g.items.map((item) => (
                  <div
                    key={item.type}
                    role="treeitem"
                    aria-level={2}
                    tabIndex={0}
                    draggable
                    className={css.itemRow}
                    data-node-type={item.type}
                    title={`${item.type}${item.info.description ? `\n${item.info.description}` : ""}`}
                    onDragStart={(e) => {
                      e.dataTransfer.setData(PALETTE_MIME, item.type);
                      e.dataTransfer.setData("text/plain", item.type);
                      e.dataTransfer.effectAllowed = "copy";
                    }}
                    onDoubleClick={() => addToActive(item)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        addToActive(item);
                      }
                    }}
                  >
                    <span className={css.name}>{item.title}</span>
                    {isNondeterministic(item.info.category) && (
                      <span className={css.badge} data-part="palette-badge">
                        {NONDETERMINISTIC_BADGE}
                      </span>
                    )}
                  </div>
                ))}
            </div>
          );
        })}
      </div>
    </>
  );
}
