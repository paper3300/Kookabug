// Ctrl+P 파일 빠른 열기 (M2 계획 2.11): 워크스페이스 그래프·target 이름 부분 일치 → Enter로 탭 열기
import { useEffect, useMemo, useRef, useState } from "react";
import { filterQuickOpen, quickOpenItems } from "../explorer/tree";
import { openTab, tabBadge } from "../store/tabs";
import { useUi } from "../store/ui";
import { useWorkspace } from "../store/workspace";
import css from "./shell.module.css";

export function QuickOpen() {
  const open = useUi((s) => s.quickOpen);
  if (!open) return null;
  return <QuickOpenBox />;
}

function QuickOpenBox() {
  const entries = useWorkspace((s) => s.entries);
  const items = useMemo(() => quickOpenItems(entries), [entries]);
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState(0);
  const matches = useMemo(() => filterQuickOpen(items, query).slice(0, 200), [items, query]);
  const box = useRef<HTMLDivElement>(null);
  const close = () => useUi.setState({ quickOpen: false });

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) close();
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, []);

  const choose = (i: number) => {
    const item = matches[i];
    if (!item) return;
    openTab({ path: item.path, kind: item.kind, graphKind: item.graphKind });
    useUi.setState({ selected: item.path });
    close();
  };

  return (
    <div ref={box} role="dialog" aria-label="파일 빠른 열기" className={css.quickOpen}>
      <label className={css.inputBox}>
        <input
          autoFocus
          type="search"
          aria-label="파일 이름"
          placeholder="파일 이름으로 찾기"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setIndex(0);
          }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setIndex((i) => Math.min(i + 1, matches.length - 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setIndex((i) => Math.max(i - 1, 0));
            } else if (e.key === "Enter") {
              e.preventDefault();
              choose(index);
            } else if (e.key === "Escape") {
              e.preventDefault();
              close();
            }
          }}
        />
      </label>
      {matches.length === 0 ? (
        <div className={css.quickEmpty}>맞는 파일이 없어요</div>
      ) : (
        <ul role="listbox" aria-label="찾은 파일" className={css.quickList}>
          {matches.map((item, i) => {
            const badge = tabBadge(item);
            return (
              <li
                key={item.path}
                role="option"
                aria-selected={i === index}
                className={css.quickItem}
                onMouseEnter={() => setIndex(i)}
                onMouseDown={(e) => {
                  e.preventDefault();
                  choose(i);
                }}
              >
                <span className={`${css.kind} ${badge.tone === "target" ? css.kindTarget : css.kindTest}`}>{badge.text}</span>
                <span>{item.name}</span>
                <span className={css.quickPath}>{item.path}</span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
