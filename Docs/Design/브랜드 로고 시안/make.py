import os, sys

OUT = os.path.dirname(os.path.abspath(__file__))
FONTS = ('<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,800'
         '&family=Fraunces:opsz,wght@9..144,600;9..144,700&family=Instrument+Serif&family=Silkscreen:wght@400;700'
         '&family=Unbounded:wght@600;700&display=block" rel="stylesheet">')

def page(name, title, lockup_light, lockup_dark, mark_light, mark_dark, note):
    html = f'''<!doctype html><html><head><meta charset="utf-8">{FONTS}
<style>
*{{box-sizing:border-box}} body{{margin:0;width:1600px;height:1000px;font-family:'Bricolage Grotesque',sans-serif;background:#fff}}
.top{{height:620px;display:flex;align-items:center;justify-content:center;background:#fff;color:#000;position:relative}}
.row{{height:380px;display:grid;grid-template-columns:800px 400px 400px}}
.p{{display:flex;align-items:center;justify-content:center;position:relative}}
.lab{{position:absolute;left:28px;top:22px;font:500 15px 'Bricolage Grotesque';letter-spacing:.06em;opacity:.55}}
</style></head><body>
<div class="top"><span class="lab">{title}</span>{lockup_light}<span class="lab" style="left:auto;right:28px;top:auto;bottom:22px;font-size:14px">{note}</span></div>
<div class="row">
 <div class="p" style="background:#000;color:#fff">{lockup_dark}</div>
 <div class="p" style="background:#fff;color:#000;border-top:1px solid #e6e6e6">{mark_light}</div>
 <div class="p" style="background:#111;color:#fff">{mark_dark}</div>
</div></body></html>'''
    open(os.path.join(OUT, f"{name}.html"), "w", encoding="utf-8").write(html)

# ---------------- L1: oo = 눈 ----------------
def eyes_svg(size, fg, bg):
    # 두 눈: 링 + 오른쪽 아래를 보는 눈동자
    return (f'<svg width="{size*2.05:.0f}" height="{size}" viewBox="0 0 205 100" aria-hidden="true">'
            f'<circle cx="50" cy="50" r="41" fill="none" stroke="{fg}" stroke-width="18"></circle>'
            f'<circle cx="155" cy="50" r="41" fill="none" stroke="{fg}" stroke-width="18"></circle>'
            f'<circle cx="62" cy="56" r="15" fill="{fg}"></circle>'
            f'<circle cx="167" cy="56" r="15" fill="{fg}"></circle></svg>')

def wm_eyes(px, fg, bg):
    o = eyes_svg(int(px * 0.56), fg, bg)
    return (f'<span style="display:inline-flex;align-items:baseline;font:800 {px}px \'Bricolage Grotesque\';'
            f'letter-spacing:-.035em;color:{fg};line-height:1">k<span style="display:inline-block;margin:0 .01em 0 .02em;'
            f'transform:translateY(.02em)">{o}</span>kabug</span>')

page("L1_eyes", "L1 · 버그를 찾는 눈",
     wm_eyes(210, "#000", "#fff"), wm_eyes(118, "#fff", "#000"),
     eyes_svg(130, "#000", "#fff"), eyes_svg(130, "#fff", "#111"),
     "oo가 'bug' 쪽을 보는 두 눈. 마크는 눈 두 개")

# ---------------- L2: K = 웃는 쿠카부라 ----------------
def kbird(size, fg, bg):
    # 왼쪽 세로획 = 뒷머리, 두 팔 = 벌린 윗부리·아랫부리, 꼭짓점 = 입
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 200 200" aria-hidden="true">'
            f'<path d="M30 186 V60 C30 34 50 16 78 16 C100 16 116 28 122 46 L176 12 C184 7 192 16 186 23 L120 96 '
            f'L184 168 C190 175 183 185 175 180 L104 130 V186 Z" fill="{fg}"></path>'
            f'<path d="M104 70 C86 70 64 76 42 88 C64 86 86 84 106 84 Z" fill="{bg}"></path>'
            f'<circle cx="95" cy="76" r="6" fill="{fg}"></circle></svg>')

def wm_k(px, fg, bg, mark):
    return (f'<span style="display:inline-flex;align-items:center;gap:{px*0.35:.0f}px;color:{fg}">{kbird(int(px*1.5), fg, bg)}'
            f'<span style="font:700 {px}px Unbounded;letter-spacing:.02em;line-height:1">KOOKABUG</span></span>')

page("L2_kbird", "L2 · K가 된 웃는 쿠카부라",
     wm_k(96, "#000", "#fff", True), wm_k(52, "#fff", "#000", True),
     kbird(220, "#000", "#fff"), kbird(220, "#fff", "#111"),
     "K의 두 팔 = 벌린 부리, 세로획 = 머리")

# ---------------- L3: 가지 위의 마스코트 ----------------
PERCH = ("M160 88 L216 98 C225 100 226 107 218 109 L166 120 "
         "C168 134 168 148 162 162 C154 182 136 194 114 194 C100 194 88 190 78 182 "
         "L52 212 L34 208 L58 164 C64 150 66 134 64 118 "
         "C62 92 82 60 118 58 C138 57 154 68 160 88 Z")
def perch(size, fg, bg):
    return (f'<svg width="{size}" height="{size}" viewBox="20 40 216 190" aria-hidden="true">'
            f'<path d="{PERCH}" fill="{fg}"></path>'
            f'<rect x="99" y="186" width="8" height="20" rx="3" fill="{fg}"></rect><rect x="118" y="186" width="8" height="20" rx="3" fill="{fg}"></rect>'
            f'<rect x="54" y="202" width="164" height="11" rx="5.5" fill="{fg}"></rect>'
            f'<path d="M150 92 C126 90 100 96 72 110 C100 106 126 104 151 104 Z" fill="{bg}"></path>'
            f'<circle cx="140" cy="97" r="5" fill="{fg}"></circle></svg>')

def wm_perch(px, fg, bg):
    return (f'<span style="display:inline-flex;align-items:flex-end;gap:{px*0.18:.0f}px;color:{fg}">{perch(int(px*1.7), fg, bg)}'
            f'<span style="font:700 {px}px Fraunces;letter-spacing:-.02em;line-height:1;margin-bottom:{px*0.12:.0f}px">Kookabug</span></span>')

page("L3_perch", "L3 · 가지 위의 마스코트",
     wm_perch(150, "#000", "#fff"), wm_perch(76, "#fff", "#000"),
     perch(230, "#000", "#fff"), perch(230, "#fff", "#111"),
     "친근한 캐릭터형. Fraunces 세리프")

# ---------------- L5: 세리프 + K 위에 앉은 작은 새 ----------------
def wm_serif(px, fg, bg):
    bird = perch(int(px * 0.42), fg, bg).replace('<rect x="54" y="202" width="164" height="11" rx="5.5"', '<rect x="54" y="202" width="0" height="0" rx="0"')
    return (f'<span style="position:relative;display:inline-block;color:{fg};font:400 {px}px \'Instrument Serif\';letter-spacing:-.01em;line-height:1">'
            f'<span style="position:absolute;left:{px*0.02:.0f}px;top:{-px*0.71:.0f}px">{bird}</span>Kookabug</span>')

page("L5_serif", "L5 · 세리프 + K에 앉은 새",
     wm_serif(250, "#000", "#fff"), wm_serif(120, "#fff", "#000"),
     perch(200, "#000", "#fff"), perch(200, "#fff", "#111"),
     "Instrument Serif. 작은 새가 K 위에 앉음")

# ---------------- L6: 원형 스탬프 ----------------
def stamp(size, fg, bg):
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 300 300" aria-hidden="true">'
            f'<circle cx="150" cy="150" r="140" fill="{fg}"></circle>'
            f'<circle cx="150" cy="150" r="98" fill="{bg}"></circle>'
            f'<path id="arc" d="M150 150 m-118 0 a118 118 0 1 1 236 0 a118 118 0 1 1 -236 0" fill="none"></path>'
            f'<text font-family="Unbounded" font-weight="700" font-size="25" letter-spacing="5" fill="{bg}">'
            f'<textPath href="#arc" startOffset="0" textLength="738" lengthAdjust="spacing">KOOKABUG · GAME QA AUTOMATION ·</textPath></text>'
            f'<g transform="translate(150 156) scale(0.68) translate(-128 -134)">'
            f'<path d="{PERCH}" fill="{fg}"></path>'
            f'<rect x="99" y="186" width="8" height="20" rx="3" fill="{fg}"></rect><rect x="118" y="186" width="8" height="20" rx="3" fill="{fg}"></rect>'
            f'<rect x="54" y="202" width="164" height="11" rx="5.5" fill="{fg}"></rect>'
            f'<path d="M150 92 C126 90 100 96 72 110 C100 106 126 104 151 104 Z" fill="{bg}"></path>'
            f'<circle cx="140" cy="97" r="5" fill="{fg}"></circle></g></svg>')

page("L6_stamp", "L6 · 원형 스탬프",
     stamp(500, "#000", "#fff"), stamp(300, "#fff", "#000"),
     stamp(260, "#000", "#fff"), stamp(260, "#fff", "#111"),
     "배지형. 둘레 글자 + 가운데 새")
print("ok")
