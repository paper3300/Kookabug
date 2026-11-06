// 플러그인 위젯 호스트 (M6 계획 3.10): config 항목 값 편집을 플러그인 위젯 iframe에 맡긴다.
// iframe은 sandbox="allow-scripts"(같은 출처 없음 = 불투명 출처), 주소는 플러그인마다 다른 호스트
// kbplugin://<id('_'는 '-')>-<지문12>/__widget.html?w=<위젯>&s=<세션>. 규칙은 widgetSession.ts, 파일·CSP는 주 프로세스
// (security.ts). 위젯이 실패하면(5초 안 ready 없음·재적재) 기본 편집기를 보인다
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useTheme } from "../store/theme";
import css from "./inspector.module.css";
import type { FieldSpec } from "./fields";
import {
  newSessionNonce,
  WIDGET_MIN_HEIGHT,
  WIDGET_READY_TIMEOUT_MS,
  widgetUrl,
  WidgetSession,
  type WidgetEndReason,
  type WidgetTheme,
} from "./widgetSession";

const THEME_COLORS = ["bg", "fg", "fg-muted", "border", "accent", "input-bg", "input-border", "status-error", "link-fg"];

function themeColors(dark: boolean): WidgetTheme {
  const style = getComputedStyle(document.documentElement);
  const colors: Record<string, string> = {};
  for (const name of THEME_COLORS) {
    const v = style.getPropertyValue(`--kb-${name}`).trim();
    if (v !== "") colors[name === "status-error" ? "error" : name] = v;
  }
  return { dark, colors };
}

const END_TEXT: Record<WidgetEndReason, string> = {
  timeout: "위젯이 응답하지 않아 기본 편집기로 보여요",
  reloaded: "위젯 문서가 다시 읽혀 기본 편집기로 보여요",
};

export function PluginWidget({
  host,
  widget,
  spec,
  label,
  value,
  readOnly,
  onCommit,
  fallback,
}: {
  host: string;
  widget: string;
  spec: FieldSpec;
  label: string;
  value: unknown;
  readOnly: boolean;
  onCommit(v: unknown): void;
  /** 위젯이 끝나면 보일 기본 편집기 */
  fallback: ReactNode;
}) {
  const frame = useRef<HTMLIFrameElement>(null);
  const dark = useTheme((s) => s.theme) === "dark";
  const [ended, setEnded] = useState<WidgetEndReason | null>(null);
  const [height, setHeight] = useState(WIDGET_MIN_HEIGHT);
  const [ready, setReady] = useState(false);
  const commit = useRef(onCommit);
  commit.current = onCommit;
  const nonce = useMemo(() => newSessionNonce(), [host, widget]);

  const session = useMemo(
    () =>
      new WidgetSession({
        session: nonce,
        widget,
        spec,
        value,
        readOnly,
        theme: themeColors(dark),
        post: (message) => frame.current?.contentWindow?.postMessage(message, "*"),
        commit: (v) => commit.current(v),
        end: (reason) => setEnded(reason),
        resize: (h) => setHeight(h),
      }),
    // 세션은 마운트(호스트·위젯·nonce)마다 하나. 값·읽기 전용·테마는 아래 효과가 넘긴다
    [nonce],
  );

  useEffect(() => {
    const onMessage = (e: MessageEvent) => {
      session.receive(e.source, frame.current?.contentWindow ?? null, e.data);
      if (session.state === "ready") setReady(true);
    };
    window.addEventListener("message", onMessage);
    const timer = window.setTimeout(() => session.timeout(), WIDGET_READY_TIMEOUT_MS);
    return () => {
      window.removeEventListener("message", onMessage);
      window.clearTimeout(timer);
      session.dispose();
    };
  }, [session]);

  useEffect(() => session.update(value, readOnly), [session, value, readOnly]);
  useEffect(() => {
    // 문서 테마(data-theme)는 App의 효과가 이 효과 뒤에 바꾼다 → 다음 프레임에 색을 읽는다
    const id = requestAnimationFrame(() => session.setTheme(themeColors(dark)));
    return () => cancelAnimationFrame(id);
  }, [session, dark]);

  if (ended !== null) {
    return (
      <>
        <div className={css.muted} data-part="widget-fallback" data-reason={ended}>
          {END_TEXT[ended]}
        </div>
        {fallback}
      </>
    );
  }
  return (
    <div className={css.widget} data-part="plugin-widget" data-widget={widget} data-ready={ready}>
      <iframe
        ref={frame}
        title={`${label} 위젯`}
        className={css.widgetFrame}
        sandbox="allow-scripts"
        referrerPolicy="strict-origin-when-cross-origin"
        src={widgetUrl(host, widget, nonce)}
        style={{ height }}
        onLoad={() => session.frameLoaded()}
      />
    </div>
  );
}
