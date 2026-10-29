import os

OUT = os.path.dirname(os.path.abspath(__file__))
B, W = "#000000", "#FFFFFF"
PERCH = ("M160 88 L216 98 C225 100 226 107 218 109 L166 120 "
         "C168 134 168 148 162 162 C154 182 136 194 114 194 C100 194 88 190 78 182 "
         "L52 212 L34 208 L58 164 C64 150 66 134 64 118 "
         "C62 92 82 60 118 58 C138 57 154 68 160 88 Z")
STRIPE = "M150 92 C126 90 100 96 72 110 C100 106 126 104 151 104 Z"

def bird(fg, bg, legs=True, branch=True, branch_x=(54, 218)):
    s = f'<path d="{PERCH}" fill="{fg}"/>'
    if legs:
        s += f'<rect x="99" y="186" width="8" height="20" rx="3" fill="{fg}"/><rect x="118" y="186" width="8" height="20" rx="3" fill="{fg}"/>'
    if branch:
        x0, x1 = branch_x
        s += f'<rect x="{x0}" y="202" width="{x1 - x0}" height="11" rx="5.5" fill="{fg}"/>'
    s += f'<path d="{STRIPE}" fill="{bg}"/><circle cx="140" cy="97" r="5" fill="{fg}"/>'
    return s

def icon(kind, uid):
    clip = f'<clipPath id="c{uid}"><rect width="256" height="256" rx="56"/></clipPath>'
    if kind == "full_dark":
        bg, body = B, f'<g transform="translate(128 130) scale(0.96) translate(-128 -136)">{bird(W, B)}</g>'
    elif kind == "full_light":
        bg, body = W, f'<g transform="translate(128 130) scale(0.96) translate(-128 -136)">{bird(B, W)}</g>'
    elif kind == "bird_only":
        bg, body = B, f'<g transform="translate(128 128) scale(1.08) translate(-130 -135)">{bird(W, B, legs=False, branch=False)}</g>'
    elif kind == "branch_edge":
        bg = B
        body = (f'<g transform="translate(128 120) scale(0.92) translate(-128 -128)">{bird(W, B, legs=True, branch=False)}</g>'
                f'<rect x="-10" y="199" width="276" height="13" fill="{W}"/>')
    elif kind == "head_dark":
        bg, body = B, f'<g transform="translate(90 128) scale(1.45) translate(-128 -110)">{bird(W, B, legs=False, branch=False)}</g>'
    elif kind == "head_light":
        bg, body = W, f'<g transform="translate(90 128) scale(1.45) translate(-128 -110)">{bird(B, W, legs=False, branch=False)}</g>'
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">'
            f'<defs>{clip}</defs><g clip-path="url(#c{uid})"><rect width="256" height="256" fill="{bg}"/>{body}</g></svg>')

KINDS = [
    ("full_dark", "A1 기본형 · 다크", "L3 마크 그대로. 새 + 가지"),
    ("full_light", "A2 기본형 · 라이트", "같은 마크, 흰 바탕"),
    ("bird_only", "B 새만", "가지·다리를 빼고 새를 크게"),
    ("branch_edge", "C 가지 확장", "가지가 아이콘 양 끝까지 이어짐"),
    ("head_dark", "D1 머리 클로즈업 · 다크", "머리와 부리를 크게, 몸은 가장자리에서 잘림"),
    ("head_light", "D2 머리 클로즈업 · 라이트", "D1의 흰 바탕 버전"),
]

uid = [0]
def svg_at(kind, px):
    uid[0] += 1
    return icon(kind, uid[0]).replace('width="256" height="256" viewBox', f'width="{px}" height="{px}" viewBox', 1)

for k, _, _ in KINDS:
    open(os.path.join(OUT, f"{k}.svg"), "w", encoding="utf-8").write(icon(k, 0))

FONTS = '<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700&family=Fraunces:opsz,wght@9..144,700&display=block" rel="stylesheet">'
cards = []
for k, t, d in KINDS:
    cards.append(f'''<div style="background:#fff;border:1px solid #e3e3e3;border-radius:14px;padding:22px;display:flex;flex-direction:column;gap:16px">
  <div style="display:flex;align-items:baseline;justify-content:space-between"><b style="font:700 19px 'Bricolage Grotesque'">{t}</b><span style="font:500 13px 'Bricolage Grotesque';color:#666">{d}</span></div>
  <div style="display:flex;gap:16px;align-items:center">
    <div style="flex:0 0 210px;height:210px;border-radius:12px;background:#9a9a9a;display:flex;align-items:center;justify-content:center">{svg_at(k, 176)}</div>
    <div style="flex:1;display:flex;flex-direction:column;gap:10px">
      <div style="height:94px;border-radius:10px;background:#f2f2f2;display:flex;align-items:center;justify-content:space-evenly">{svg_at(k,64)}{svg_at(k,48)}{svg_at(k,32)}{svg_at(k,24)}{svg_at(k,16)}</div>
      <div style="height:94px;border-radius:10px;background:#1c1c1c;display:flex;align-items:center;justify-content:space-evenly">{svg_at(k,64)}{svg_at(k,48)}{svg_at(k,32)}{svg_at(k,24)}{svg_at(k,16)}</div>
    </div>
  </div></div>''')

def taskbar(bg, fg):
    items = "".join(f'<div style="width:44px;height:40px;border-radius:4px;display:flex;align-items:center;justify-content:center;background:{"rgba(127,127,127,.18)" if i==0 else "transparent"}">{svg_at(k,24)}</div>' for i,(k,_,_) in enumerate(KINDS))
    return f'<div style="height:48px;border-radius:10px;background:{bg};display:flex;align-items:center;justify-content:center;gap:6px;color:{fg}">{items}</div>'

html = f'''<!doctype html><html><head><meta charset="utf-8">{FONTS}</head>
<body style="margin:0;width:1600px;background:#ececec;font-family:'Bricolage Grotesque',sans-serif">
<div style="padding:40px 48px;display:flex;flex-direction:column;gap:24px">
  <div style="display:flex;align-items:flex-end;justify-content:space-between">
    <div><div style="font:700 34px Fraunces">Kookabug 앱 아이콘</div>
    <div style="font:500 15px 'Bricolage Grotesque';color:#555;margin-top:6px">L3 가지 위의 마스코트에서 뽑은 후보 · 오른쪽 두 줄은 64 / 48 / 32 / 24 / 16px (밝은 · 어두운 배경)</div></div>
  </div>
  <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:20px">{"".join(cards)}</div>
  <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:20px">
    <div><div style="font:500 13px 'Bricolage Grotesque';color:#555;margin-bottom:8px">작업 표시줄 · 어두운 테마 (24px) · 왼쪽부터 A1 A2 B C D1 D2</div>{taskbar("#202020", "#fff")}</div>
    <div><div style="font:500 13px 'Bricolage Grotesque';color:#555;margin-bottom:8px">작업 표시줄 · 밝은 테마 (24px)</div>{taskbar("#f3f3f3", "#000")}</div>
  </div>
</div></body></html>'''
open(os.path.join(OUT, "sheet.html"), "w", encoding="utf-8").write(html)
print("ok")
