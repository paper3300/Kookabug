// 검사 창 모니터 (KOOKABUG_TEST_DISPLAY, tools/kb_testing/display.py와 같은 값: left·right·primary·"x,y").
// e2e 도우미(app.ts)가 Electron 주 프로세스에 `-r`로 먼저 싣는다 — 앱 코드를 바꾸지 않고, 창을 만드는
// 순간(browser-window-created) 그 모니터 작업 영역으로 옮겨 주 모니터에 잠깐도 뜨지 않게 한다.
// 창이 작업 영역보다 넓으면(1080 폭 세로 모니터에 1440 폭 시안 판) 크기는 그대로 두고 주 모니터
// 반대쪽으로 넘친다 — 화면 비교는 창 내용 크기만 보므로 그림이 같고, 넘친 부분이 주 모니터를 가리지 않는다
"use strict";

const spec = (process.env.KOOKABUG_TEST_DISPLAY || "").trim().toLowerCase();
// 프레임 없는 창도 둘레에 보이지 않는 크기 조절 테두리(8 DIP)가 있다: 그만큼 더 떨어뜨린다
const EDGE = 8;

if (spec !== "") {
  const { app, screen } = require("electron");

  const pick = () => {
    const all = screen.getAllDisplays();
    if (spec === "left") return all.reduce((a, b) => (b.bounds.x < a.bounds.x ? b : a));
    if (spec === "right") {
      return all.reduce((a, b) => (b.bounds.x + b.bounds.width > a.bounds.x + a.bounds.width ? b : a));
    }
    if (spec === "primary") return screen.getPrimaryDisplay();
    const point = /^\s*(-?\d+)\s*,\s*(-?\d+)\s*$/.exec(spec);
    if (point === null) throw new Error(`KOOKABUG_TEST_DISPLAY=${spec}: left·right·primary 또는 'x,y'`);
    return screen.getDisplayNearestPoint({ x: Number(point[1]), y: Number(point[2]) });
  };

  const place = (win) => {
    if (win.isDestroyed() || win.isMaximized() || win.isFullScreen()) return;
    const display = pick();
    const work = display.workArea;
    const primary = screen.getPrimaryDisplay().bounds;
    const [width, height] = win.getSize();
    let x = work.x + Math.floor((work.width - width) / 2);
    if (width + 2 * EDGE > work.width) {
      // 주 모니터 왼쪽 모니터면 오른쪽 끝을 맞춰 왼쪽으로 넘친다, 아니면 왼쪽 끝을 맞춘다
      x = display.bounds.x + display.bounds.width <= primary.x ? work.x + work.width - width - EDGE : work.x + EDGE;
    }
    const y = work.y + Math.max(0, Math.floor((work.height - height) / 2));
    win.setPosition(x, y);
  };

  // 검사 도우미(setContentSize)가 크기를 바꾼 뒤 다시 부른다
  globalThis.__kbPlaceWindow = place;
  app.on("browser-window-created", (_event, win) => {
    place(win);
    win.once("ready-to-show", () => place(win));
  });
}
