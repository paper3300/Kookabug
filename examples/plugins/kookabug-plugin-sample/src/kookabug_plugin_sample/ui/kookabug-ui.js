// @kookabug/ui-sdk — Kookabug 인스펙터 값 편집 위젯 SDK (MIT). 의존성 없는 ES 모듈 하나.
//
// 위젯은 플러그인 `ui/` 폴더의 index.js가 그린다. 앱은 위젯을 샌드박스 iframe(불투명 출처)에 띄우고
// postMessage로만 이야기한다 (Kookabug M6 계획 3.10):
//   위젯 → 앱  {kb:"ready"|"change"|"resize", session, …}
//   앱 → 위젯  {kb:"init", api:1, session, widget, value, schema, readOnly, theme} · {kb:"value"} · {kb:"theme"}
// 세션은 주소의 `s` 값이다. 앱은 지금 iframe에서 온, 그 세션의 메시지만 받는다.
// 위젯은 네트워크·파일·RPC에 접근할 수 없다 (CSP). 이 파일은 플러그인 ui 폴더에 복사해 쓴다.

export const API_VERSION = 1;

/**
 * @param {{
 *   onInit?: (ctx: {widget: string, value: unknown, schema: Record<string, unknown>, readOnly: boolean, theme: Record<string, unknown>}) => void,
 *   onValue?: (value: unknown, readOnly: boolean) => void,
 *   onTheme?: (theme: Record<string, unknown>) => void,
 *   autoHeight?: boolean,
 * }} handlers
 */
export function defineWidget(handlers = {}) {
  const session = new URLSearchParams(location.search).get("s") ?? "";
  const host = window.parent;
  let started = false;
  let lastHeight = -1;

  const post = (message) => host.postMessage({ ...message, session }, "*");

  window.addEventListener("message", (event) => {
    if (event.source !== host) return;
    const data = event.data;
    if (data === null || typeof data !== "object" || data.session !== session) return;
    if (data.kb === "init" && !started) {
      started = true;
      applyTheme(data.theme);
      handlers.onInit?.({
        widget: String(data.widget ?? ""),
        value: data.value,
        schema: data.schema ?? {},
        readOnly: data.readOnly === true,
        theme: data.theme ?? {},
      });
      measure();
    } else if (data.kb === "value" && started) {
      handlers.onValue?.(data.value, data.readOnly === true);
    } else if (data.kb === "theme" && started) {
      applyTheme(data.theme);
      handlers.onTheme?.(data.theme ?? {});
    }
  });

  function setHeight(height) {
    const h = Math.ceil(Number(height));
    if (!Number.isFinite(h) || h === lastHeight) return;
    lastHeight = h;
    post({ kb: "resize", height: h });
  }

  function measure() {
    if (handlers.autoHeight === false) return;
    setHeight(document.documentElement.scrollHeight);
  }

  if (handlers.autoHeight !== false && typeof ResizeObserver === "function") {
    new ResizeObserver(measure).observe(document.documentElement);
  }

  post({ kb: "ready" });

  return {
    /** 값을 바꾼다. 앱이 그 항목 스키마로 검사하고, 읽기 전용(실행 중·기록 보기)이면 버린다 */
    setValue(value) {
      post({ kb: "change", value });
    },
    setHeight,
  };
}

// 앱 테마 색을 CSS 변수(--kb-*)로 둔다: 위젯이 앱과 같은 색을 쓰게
function applyTheme(theme) {
  if (theme === null || typeof theme !== "object") return;
  const root = document.documentElement;
  root.dataset.theme = theme.dark ? "dark" : "light";
  const colors = theme.colors;
  if (colors === null || typeof colors !== "object") return;
  for (const [key, value] of Object.entries(colors)) {
    if (/^[a-z0-9-]+$/.test(key) && typeof value === "string") root.style.setProperty(`--kb-${key}`, value);
  }
}
