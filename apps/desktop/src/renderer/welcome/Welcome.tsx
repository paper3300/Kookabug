// 시작 화면 (M2 계획 2.10 "폴더 열기", 2.11 Setup0Welcome). 로고·워드마크·소개 글·"프로젝트 열기"·
// 최근 프로젝트·테마 고르기. M8 B7: "새 프로젝트 만들기" → 첫 프로젝트 마법사 (기존 "프로젝트 열기" 단추는 그대로)
import { useEffect } from "react";
import { WindowControls } from "../app/WindowControls";
import { useTheme, type ThemeMode } from "../store/theme";
import { openFolder, openRecent, useWorkspace } from "../store/workspace";
import { EnterIcon, LogoMark } from "../theme/icons";
import { WizardHost } from "../wizard/Wizard";
import { openNewWizard, useWizard } from "../wizard/wizardStore";
import css from "./welcome.module.css";

const MODES: [ThemeMode, string][] = [
  ["system", "시스템"],
  ["light", "라이트"],
  ["dark", "다크"],
];

export function ThemeToggle() {
  const mode = useTheme((s) => s.mode);
  const setMode = useTheme((s) => s.setMode);
  return (
    <div role="group" aria-label="테마" className={css.toggle}>
      {MODES.map(([value, label]) => (
        <button key={value} type="button" aria-pressed={mode === value} onClick={() => void setMode(value)}>
          {label}
        </button>
      ))}
    </div>
  );
}

function ToolPreview() {
  return (
    <div aria-hidden="true" className={css.preview}>
      <div className={css.previewActivity}>
        <span className={css.previewIcon} />
        <span className={css.previewIconDim} />
        <span className={css.previewIconDim} />
      </div>
      <div className={css.previewSide}>
        <span style={{ width: 70 }} className={css.previewBar} />
        <span style={{ width: 120 }} className={css.previewBarDim} />
        <span style={{ width: 100 }} className={css.previewBarDim} />
        <span style={{ width: 110 }} className={css.previewBarDim} />
      </div>
      <div className={css.previewCanvas}>
        <div className={css.previewNode} style={{ left: 40, top: 50 }}>
          <div className={css.headBlue} />
        </div>
        <div className={css.previewNode} style={{ left: 210, top: 90 }}>
          <div className={css.headGreen} />
        </div>
        <div className={css.previewNode} style={{ left: 380, top: 50 }}>
          <div className={css.headPurple} />
        </div>
        <div className={css.previewWire} style={{ left: 160 }} />
        <div className={css.previewWire} style={{ left: 330 }} />
      </div>
      <div className={css.previewAgent}>
        <span className={css.previewPill} />
        <span style={{ width: 140 }} className={css.previewBarDim} />
        <span style={{ width: 120 }} className={css.previewBarDim} />
      </div>
    </div>
  );
}

export function Welcome() {
  const recent = useWorkspace((s) => s.recent);
  const openError = useWorkspace((s) => s.openError);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Enter" && e.target === document.body && !useWizard.getState().open) void openFolder();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className={css.screen} data-screen="welcome">
      <div className={css.dragBar}>
        <WindowControls height={32} />
      </div>
      <ThemeToggle />
      <div className={css.hero}>
        <div className={css.brand}>
          <LogoMark className={css.logo} cutout="var(--kb-welcome-bg)" width={73} height={64} />
          <span className={css.wordmark}>Kookabug</span>
        </div>
        <h1 className={css.title}>Kookabug에 오신 걸 환영해요</h1>
        <p className={css.lead}>
          게임 화면을 보고, 누르고, 확인하는 QA 자동화를
          <br />
          <span className={`${css.chip} ${css.chipGraph}`}>노드 그래프</span>{" "}
          <span className={`${css.chip} ${css.chipRecord}`}>녹화</span>{" "}
          <span className={`${css.chip} ${css.chipAgent}`}>에이전트</span>로 만들어요.
        </p>
        <div className={css.actions}>
          <button type="button" className={css.primary} onClick={() => void openFolder()}>
            프로젝트 열기 <EnterIcon />
          </button>
          {/* M8 B7 첫 프로젝트 마법사 (0단계 = 이 화면의 두 갈래) */}
          <button type="button" className={css.secondary} data-part="new-project" onClick={openNewWizard}>
            새 프로젝트 만들기
          </button>
          {openError && (
            <p role="alert" className={css.error}>
              {openError.reason === "not_workspace" ? "Kookabug 프로젝트가 아닙니다" : "폴더를 찾을 수 없습니다"}
              <span className={css.errorPath}>{openError.path}</span>
            </p>
          )}
        </div>
      </div>
      {recent.length > 0 ? (
        <section aria-label="최근 프로젝트" className={css.recent}>
          <h2 className={css.recentTitle}>최근 프로젝트</h2>
          <ul className={css.recentList}>
            {recent.map((r) => (
              <li key={r.path}>
                <button type="button" className={css.recentItem} title={r.path} onClick={() => void openRecent(r.path)}>
                  <span className={css.recentName}>{r.name}</span>
                  <span className={css.recentPath}>{r.path}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : (
        <ToolPreview />
      )}
      <WizardHost />
    </div>
  );
}
