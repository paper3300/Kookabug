// 시안 PNG와 앱 PNG를 나란히 놓은 비교 PNG를 만든다 (M2 계획 2.12 "나란히 비교").
//
//   node tools/design-ref/compare.mjs <화면 id...>
//     기준 build/design-ref/<시안>.png, 앱 build/ui-shots/<id>-<테마>.png
//     → build/ui-compare/<id>-<테마>.png
//
// 이미지 라이브러리 없이 HTML 한 장을 Edge로 찍는다
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { launchBrowser, OUT_DIR as REF_DIR, REPO_ROOT } from "./render.mjs";

export const SHOTS_DIR = path.join(REPO_ROOT, "build", "ui-shots");
export const COMPARE_DIR = path.join(REPO_ROOT, "build", "ui-compare");

// 앱 화면 id → 테마별 시안. UI 작업(T7~T12)이 늘린다
export const SCREENS = {
  main: { dark: "Main", light: "MainLight" },
  welcome: { dark: "Setup0Welcome", light: "Setup0WelcomeLight" },
  // 앱 틀(캔버스 내용 제외), T7
  "shell-empty": { dark: "Main", light: "MainLight" },
  // 캔버스(노드·핀·연결선·미니맵·문제 패널), T8
  "main-canvas": { dark: "Main", light: "MainLight" },
  // 팔레트(사이드바 "노드" 섹션)·저장 안 됨 탭, T9
  "main-palette": { dark: "Main", light: "MainLight" },
  // 시안에 없는 편집 중 상태 (끌어 놓기·핀 잇기): 시안 언어(색·글자)와 나란히 본다, T9
  "palette-drag": { dark: "Main", light: "MainLight" },
  "connect-drag": { dark: "Main", light: "MainLight" },
  "close-confirm": { dark: "Main", light: "MainLight" },
  // 속성 편집기(시안에 없는 화면, U1): 에이전트 패널 자리에 사이드바 섹션·입력 상자 모양, T10
  inspector: { dark: "Main", light: "MainLight" },
  "inspector-link": { dark: "Main", light: "MainLight" },
  // 실행 중간 시점(강조 노드·상태 줄·실행 로그·파란 상태 바), T11
  "main-running": { dark: "Main", light: "MainLight" },
  // 디버그 툴바(시안 "실행 제어")·정지 단추 이동·브레이크포인트 점, 멈춘 상태(시안에 없음, U1·U2), M3 T9
  "main-debug": { dark: "Main", light: "MainLight" },
  "main-debug-paused": { dark: "Main", light: "MainLight" },
  // target 편집기, T12. Recorder는 다크 시안뿐이라 라이트 앱 화면도 다크 Recorder와 나란히 본다(배치·요소 대조)
  target: { dark: "Recorder", light: "Recorder" },
  // target 편집기 확장(민감 대상·색 허용치·검색 범위 숫자·글자 읽기·다른 배율), M4 T11. 시안에 없는 요소(U14)라 배치·색만 대조
  "target-ext": { dark: "Recorder", light: "Recorder" },
  // 녹화 화면 전체(사이드바·REC 탭·빨간 상태 바), M4 T9·T10. 시안에 없는 상태(녹화 전·일시정지·정지 뒤·오류)는 같은 시안과
  // 나란히 본다(사람 확인용)
  recorder: { dark: "Recorder", light: "Recorder" },
  "recorder-idle": { dark: "Recorder" },
  "recorder-paused": { dark: "Recorder" },
  "recorder-stopped": { dark: "Recorder" },
  "recorder-error": { dark: "Recorder" },
  // 기록 뷰어(사이드바 실행 목록·RUN 머리·타임라인·스크린샷 줄·후보 표), M3 T10. RunViewer도 다크 시안뿐이다
  runviewer: { dark: "RunViewer", light: "RunViewer" },
  // 기록 뷰어 2(머리 단추·하위 탭·회차 막대·"스크린샷 | 영상" 전환·비교 상자·보관 문구), M3 T11. 통계·비교 탭 내용은
  // 시안에 없어 나란히 볼 기준이 같은 RunViewer다
  "runviewer-compare": { dark: "RunViewer", light: "RunViewer" },
  "runviewer-stats": { dark: "RunViewer", light: "RunViewer" },
  "runviewer-comparetab": { dark: "RunViewer", light: "RunViewer" },
  // 에이전트 패널(오른쪽 속성 | 에이전트 탭, 연결 화면·대화·승인 카드·ACP 권한 카드), 판단 노드, RUN 탭 분석 단추, M5 B4·B5.
  // 시안 Main 오른쪽 에이전트 패널·"Agent 판단 · CLI" 노드와 나란히 본다. 권한 설정(시안 Permissions)은 렌더러가 아직 못 그린다
  "panel-empty": { dark: "Main" },
  "panel-chat": { dark: "Main" },
  "panel-approval": { dark: "Main" },
  "panel-acp-permission": { dark: "Main" },
  "agent-judge": { dark: "Main" },
  "runviewer-analyze": { dark: "RunViewer" },
  // 화면 지도(사이드바 화면 목록·선택·확인 전, MAP 탭 카드·간선·범례·확대, 상태 바), M7 B5. 시안 ScreenMap은 다크뿐이라
  // 라이트 앱 화면도 다크 시안과 나란히 본다(배치·요소 대조). 승격 대화 상자·보호 카드는 시안에 없는 상태
  screenmap: { dark: "ScreenMap", light: "ScreenMap" },
  "screenmap-promote": { dark: "ScreenMap" },
  "screenmap-protected": { dark: "ScreenMap" },
  // 첫 프로젝트 마법사(창 1120×720 전체 겹 화면), M8 B7. 확정 시안은 5·6·9·9NoAgent, 나머지 단계는 같은 배치의
  // 옛 첫 실행 시안(Setup0~3)과 나란히 본다. 첫 실행 순서는 0·1·2·(3)·5·6·9(UX5): 3은 점검에 경고가 있어 머물 때만
  // 찍히고, 계정(4)·자동화 정책(7)·기록(8)은 설정 도우미에서만 열려 찍지 않는다
  wizard0: { dark: "Setup0Welcome" },
  wizard1: { dark: "Setup1Project" },
  wizard2: { dark: "Setup2Game" },
  wizard3: { dark: "Setup3Check" },
  wizard5: { dark: "Wizard5Agent" },
  wizard6: { dark: "Wizard6Sources" },
  wizard9: { dark: "Wizard9Init" },
  "wizard9-noagent": { dark: "Wizard9NoAgent" },
};

function pngSize(file) {
  const png = fs.readFileSync(file);
  return { width: png.readUInt32BE(16), height: png.readUInt32BE(20) };
}

function escapeHtml(s) {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
}

export async function compare(browser, id, theme, { refFile, appFile, outFile }) {
  const ref = pngSize(refFile);
  const shot = pngSize(appFile);
  const label = 28;
  const gap = 16;
  const width = ref.width + shot.width + gap * 3;
  const height = Math.max(ref.height, shot.height) + label + gap * 2;
  const cell = (title, file, size) =>
    `<figure><figcaption>${escapeHtml(title)} · ${size.width}×${size.height}</figcaption>` +
    `<img src="${pathToFileURL(file).href}" width="${size.width}" height="${size.height}"></figure>`;
  const html = `<!doctype html><meta charset="utf-8"><style>
body{margin:0;background:#808080;font:14px "Segoe UI",sans-serif;color:#fff}
main{display:flex;gap:${gap}px;padding:${gap}px}
figure{margin:0}figcaption{height:${label}px;line-height:${label}px}
img{display:block}
</style><main>${cell(`시안 ${path.basename(refFile, ".png")} (${theme})`, refFile, ref)}${cell(`앱 ${id} (${theme})`, appFile, shot)}</main>`;
  const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 1 });
  try {
    // file:// 이미지를 읽으려고 임시 HTML 파일로 연다
    fs.mkdirSync(path.dirname(outFile), { recursive: true });
    const htmlFile = outFile.replace(/\.png$/, ".html");
    fs.writeFileSync(htmlFile, html);
    await page.goto(pathToFileURL(htmlFile).href);
    await page.waitForFunction(() => [...document.images].every((i) => i.complete && i.naturalWidth > 0));
    await page.screenshot({ path: outFile });
    fs.rmSync(htmlFile);
  } finally {
    await page.close();
  }
  return outFile;
}

async function main(ids) {
  if (ids.length === 0) throw new Error(`화면 id를 준다: ${Object.keys(SCREENS).join(", ")}`);
  const browser = await launchBrowser();
  let missing = 0;
  try {
    for (const id of ids) {
      const themes = SCREENS[id];
      if (!themes) throw new Error(`모르는 화면 id: ${id}`);
      for (const [theme, refName] of Object.entries(themes)) {
        const refFile = path.join(REF_DIR, `${refName}.png`);
        const appFile = path.join(SHOTS_DIR, `${id}-${theme}.png`);
        for (const f of [refFile, appFile]) {
          if (!fs.existsSync(f)) {
            console.error(`없다: ${path.relative(REPO_ROOT, f)}`);
            missing++;
          }
        }
        if (!fs.existsSync(refFile) || !fs.existsSync(appFile)) continue;
        const outFile = path.join(COMPARE_DIR, `${id}-${theme}.png`);
        await compare(browser, id, theme, { refFile, appFile, outFile });
        console.log(path.relative(REPO_ROOT, outFile));
      }
    }
  } finally {
    await browser.close();
  }
  if (missing) process.exit(1);
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  main(process.argv.slice(2)).catch((err) => {
    console.error(err.message ?? err);
    process.exit(1);
  });
}
