// 위젯 격리 탐침. 처음 값(검사가 그래프에 넣은 주소)으로 시도하고 결과를 setValue로 알린다.
//   fetch: 그 주소 fetch          → "fetch:ok" | "fetch:blocked"
//   other: 그 주소 동적 import    → "other:loaded" | "other:blocked"
//   nav:   그 주소로 자기 프레임 이동 시도 → 1초 뒤 살아 있으면 "nav:alive",
//          이어 문서를 다시 써 load를 한 번 더 일으키고(재적재) 옛 세션으로 "nav:after-reload"를 보낸다
import { defineWidget } from "./kookabug-ui.js";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const status = document.createElement("div");
status.textContent = "probe";
document.body.append(status);

let widget = null;

async function run(name, target) {
  const url = String(target ?? "");
  if (name.endsWith(".fetch")) {
    try {
      await fetch(url);
      widget.setValue("fetch:ok");
    } catch {
      widget.setValue("fetch:blocked");
    }
  } else if (name.endsWith(".other")) {
    try {
      await import(url);
      widget.setValue("other:loaded");
    } catch {
      widget.setValue("other:blocked");
    }
  } else if (name.endsWith(".nav")) {
    try {
      location.href = url;
    } catch {
      /* 막히면 예외일 수도 있다 */
    }
    await sleep(1000);
    widget.setValue("nav:alive");
    await sleep(500);
    const post = widget.setValue;
    document.open();
    document.write("<p>rewritten</p>");
    document.close();
    await sleep(500);
    post("nav:after-reload");
  }
}

widget = defineWidget({
  autoHeight: false,
  onInit: ({ widget: name, value }) => {
    status.textContent = name;
    // 주소일 때만 시도한다 (결과 글자 "fetch:blocked" 등이 다시 오면 그대로 둔다)
    if (typeof value === "string" && /^(https?|kbplugin):\/\//.test(value)) void run(name, value);
  },
});
