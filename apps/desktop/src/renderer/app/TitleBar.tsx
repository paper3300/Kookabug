// 타이틀 바 (시안 Main): 로고·메뉴·명령 검색 자리·창 버튼. 명령 검색은 파일 빠른 열기만 한다 (2.11).
// 시안의 "플러그인" 메뉴는 M6까지 숨긴다 (2.10 "창", U3)
import { useEffect, useRef, useState } from "react";
import { canRedo, canUndo, redoEdit, saveDoc, undoEdit, useDocuments } from "../store/documents";
import { requestCloseTab } from "../store/editing";
import { useTabs } from "../store/tabs";
import { useTheme, type ThemeMode } from "../store/theme";
import { useUi } from "../store/ui";
import { closeWorkspace, openFolder, useWorkspace } from "../store/workspace";
import { LogoMark, SearchIcon } from "../theme/icons";
import css from "./shell.module.css";
import { WindowControls } from "./WindowControls";

interface MenuItem {
  label: string;
  shortcut?: string;
  checked?: boolean;
  disabled?: boolean;
  run?: () => void;
}
type MenuEntry = MenuItem | "separator";

function useMenus(): [string, MenuEntry[]][] {
  const mode = useTheme((s) => s.mode);
  const setMode = useTheme((s) => s.setMode);
  const hasWorkspace = useWorkspace((s) => s.root !== null);
  const active = useTabs((s) => s.active);
  const graph = useTabs((s) => (s.tabs.find((t) => t.path === s.active)?.kind === "graph" ? s.active : null));
  const doc = useDocuments((s) => (graph === null ? undefined : s.docs.get(graph)));
  const inspectorOpen = useUi((s) => s.inspectorOpen);
  const theme = (value: ThemeMode, label: string): MenuItem => ({
    label: `테마: ${label}`,
    checked: mode === value,
    run: () => void setMode(value),
  });
  return [
    [
      "파일",
      [
        { label: "프로젝트 열기…", shortcut: "Ctrl+O", run: () => void openFolder() },
        { label: "파일 빠른 열기", shortcut: "Ctrl+P", disabled: !hasWorkspace, run: () => useUi.setState({ quickOpen: true }) },
        "separator",
        {
          label: "저장",
          shortcut: "Ctrl+S",
          disabled: doc?.status !== "ready",
          run: () => graph !== null && void saveDoc(graph),
        },
        { label: "탭 닫기", shortcut: "Ctrl+W", disabled: active === null, run: () => active && void requestCloseTab(active) },
        {
          label: "프로젝트 닫기",
          disabled: !hasWorkspace,
          run: () => void closeWorkspace(),
        },
        "separator",
        { label: "끝내기", run: () => void window.kookabug.app.windowControl("close") },
      ],
    ],
    [
      "편집",
      [
        { label: "실행 취소", shortcut: "Ctrl+Z", disabled: !canUndo(doc), run: () => graph !== null && undoEdit(graph) },
        { label: "다시 실행", shortcut: "Ctrl+Y", disabled: !canRedo(doc), run: () => graph !== null && redoEdit(graph) },
      ],
    ],
    [
      "보기",
      [
        theme("system", "시스템"),
        theme("light", "라이트"),
        theme("dark", "다크"),
        "separator",
        { label: "속성 패널", checked: inspectorOpen, run: () => useUi.setState({ inspectorOpen: !inspectorOpen }) },
      ],
    ],
    [
      "실행",
      [
        { label: "실행", shortcut: "F5", disabled: true },
        { label: "정지", shortcut: "Shift+F5", disabled: true },
      ],
    ],
    ["도움말", [{ label: "Kookabug 0.1", disabled: true }]],
  ];
}

function Menus() {
  const menus = useMenus();
  const [open, setOpen] = useState<string | null>(null);
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    if (open === null) return;
    const close = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(null);
    };
    const key = (e: KeyboardEvent) => e.key === "Escape" && setOpen(null);
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", key);
    return () => {
      window.removeEventListener("mousedown", close);
      window.removeEventListener("keydown", key);
    };
  }, [open]);
  return (
    <nav aria-label="메뉴" className={css.menus} ref={ref}>
      {menus.map(([title, items]) => (
        <div key={title} style={{ position: "relative" }}>
          <button
            type="button"
            className={css.menuButton}
            aria-haspopup="menu"
            aria-expanded={open === title}
            onClick={() => setOpen(open === title ? null : title)}
            onMouseEnter={() => open !== null && setOpen(title)}
          >
            {title}
          </button>
          {open === title && (
            <div role="menu" aria-label={title} className={css.menu}>
              {items.map((item, i) =>
                item === "separator" ? (
                  <div key={i} role="separator" className={css.menuSeparator} />
                ) : (
                  <button
                    key={item.label}
                    type="button"
                    role={item.checked === undefined ? "menuitem" : "menuitemradio"}
                    aria-checked={item.checked}
                    disabled={item.disabled}
                    className={css.menuItem}
                    onClick={() => {
                      setOpen(null);
                      item.run?.();
                    }}
                  >
                    <span className={css.menuCheck}>{item.checked ? "✓" : ""}</span>
                    {item.label}
                    {item.shortcut && <span className={css.menuShortcut}>{item.shortcut}</span>}
                  </button>
                ),
              )}
            </div>
          )}
        </div>
      ))}
    </nav>
  );
}

export function TitleBar() {
  const name = useWorkspace((s) => s.name);
  return (
    <header className={css.titlebar} data-part="titlebar">
      <div className={css.logo} aria-hidden="true">
        <LogoMark width={18} height={16} cutout="var(--kb-titlebar-bg)" />
      </div>
      <Menus />
      <div className={css.spacer} />
      <button
        type="button"
        aria-label="파일 빠른 열기"
        className={css.search}
        onClick={() => useUi.setState({ quickOpen: true })}
      >
        <SearchIcon />
        <span className={css.searchText}>{name ? `${name} — 파일 검색 (Ctrl+P)` : "파일 검색 (Ctrl+P)"}</span>
      </button>
      <div className={css.spacer} />
      <WindowControls />
    </header>
  );
}
