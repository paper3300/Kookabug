// 예제 UI 확장: 색 위젯 (sample.color). kookabug-ui.js는 @kookabug/ui-sdk의 index.js 사본이다
import { defineWidget } from "./kookabug-ui.js";

const SWATCHES = ["#3366ff", "#22aa66", "#e5a50a", "#e01b24", "#9141ac", "#000000", "#ffffff"];
const HEX = /^#[0-9a-fA-F]{6}$/;

const style = document.createElement("style");
style.textContent = `
  :root { color-scheme: dark; font: 12px system-ui, sans-serif; }
  :root[data-theme="light"] { color-scheme: light; }
  body { margin: 0; padding: 1px 0 4px; color: var(--kb-fg, #ccc); background: transparent; }
  .row { display: flex; align-items: center; gap: 6px; }
  input[type=color] { width: 28px; height: 24px; padding: 0; border: 1px solid var(--kb-border, #444); border-radius: 4px; background: none; }
  input[type=text] { flex: 1; min-width: 0; height: 22px; padding: 0 6px; border: 1px solid var(--kb-border, #444);
    border-radius: 4px; background: var(--kb-input-bg, #2a2a2a); color: inherit; font: 12px ui-monospace, monospace; }
  input[aria-invalid=true] { border-color: var(--kb-error, #e05252); }
  .swatches { display: flex; gap: 4px; margin-top: 6px; }
  .swatches button { width: 18px; height: 18px; border-radius: 4px; border: 1px solid var(--kb-border, #444); padding: 0; cursor: pointer; }
  .swatches button[aria-pressed=true] { outline: 2px solid var(--kb-accent, #3794ff); outline-offset: 1px; }
  :disabled { opacity: .55; cursor: default; }
`;
document.head.append(style);

const picker = Object.assign(document.createElement("input"), { type: "color" });
picker.setAttribute("aria-label", "색");
const text = Object.assign(document.createElement("input"), { type: "text", spellcheck: false });
text.setAttribute("aria-label", "색 코드");
const row = document.createElement("div");
row.className = "row";
row.append(picker, text);
const swatches = document.createElement("div");
swatches.className = "swatches";
const buttons = SWATCHES.map((c) => {
  const b = document.createElement("button");
  b.type = "button";
  b.title = c;
  b.style.background = c;
  b.dataset.color = c;
  swatches.append(b);
  return b;
});
document.body.append(row, swatches);

let current = "";

function show(value, readOnly) {
  current = typeof value === "string" && HEX.test(value) ? value.toLowerCase() : "";
  picker.value = current || "#000000";
  text.value = typeof value === "string" ? value : "";
  text.setAttribute("aria-invalid", "false");
  for (const el of [picker, text, ...buttons]) el.disabled = readOnly;
  for (const b of buttons) b.setAttribute("aria-pressed", String(b.dataset.color === current));
}

const widget = defineWidget({
  onInit: ({ value, schema, readOnly }) => show(value ?? schema.default, readOnly),
  onValue: (value, readOnly) => show(value, readOnly),
});

function commit(value) {
  const v = value.trim().toLowerCase();
  if (!HEX.test(v)) {
    text.setAttribute("aria-invalid", "true");
    return;
  }
  if (v !== current) widget.setValue(v);
}

picker.addEventListener("change", () => commit(picker.value));
text.addEventListener("keydown", (e) => {
  if (e.key === "Enter") commit(text.value);
});
text.addEventListener("blur", () => commit(text.value));
for (const b of buttons) b.addEventListener("click", () => commit(b.dataset.color));
