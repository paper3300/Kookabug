# @kookabug/ui-sdk

Kookabug 플러그인의 인스펙터 값 편집 위젯을 만드는 SDK. MIT 라이선스 (본체는 Apache-2.0). 의존성 없는 ES 모듈 하나다.

## 쓰는 법

1. 노드 config에 위젯을 단다 (Python SDK):

   ```python
   from kookabug_sdk import Config, Widget, node

   @node(type="acme.color.pick", ..., config={"color": Config(str, default="#3366ff", ui=Widget("color"))})
   ```

2. `pyproject.toml`의 `[tool.kookabug]`에 `ui = "ui"`를 적고, 패키지 안 `ui/index.js`에서 그린다.
   위젯 iframe은 자기 플러그인 `ui/` 폴더의 파일만 읽을 수 있으므로 이 SDK의 `index.js`를
   `ui/kookabug-ui.js` 같은 이름으로 **복사**해 import한다 (번들러로 묶어도 된다).

   ```js
   import { defineWidget } from "./kookabug-ui.js";

   const input = document.createElement("input");
   input.type = "color";
   document.body.append(input);
   const widget = defineWidget({
     onInit({ value, readOnly }) {
       input.value = String(value ?? "#000000");
       input.disabled = readOnly;
     },
     onValue(value, readOnly) {
       input.value = String(value);
       input.disabled = readOnly;
     },
   });
   input.addEventListener("change", () => widget.setValue(input.value));
   ```

한 플러그인의 위젯은 모두 같은 `index.js`가 그린다. `init`의 `widget`(`<플러그인>.<이름>`)으로 나눈다.

## 지켜지는 것

- 위젯은 샌드박스 iframe(불투명 출처)에서 돈다. 네트워크·파일·앱 RPC·다른 노드·다른 플러그인 자원에 접근할 수 없다 (CSP `default-src 'none'`)
- 위젯 프레임은 다른 주소로 이동할 수 없다. 문서를 다시 읽으면 세션이 끝나고 앱은 기본 편집기로 돌아간다
- `setValue`의 값은 앱이 그 항목 스키마로 검사하고, 실행 중·기록 보기(읽기 전용)이면 버린다
- 5초 안에 `defineWidget`을 부르지 않으면 앱은 기본 편집기를 보인다
- 비밀값 타입 항목에는 위젯을 쓸 수 없다 (빌드 오류, 앱도 거부)

## API

- `defineWidget({ onInit, onValue, onTheme, autoHeight })` → `{ setValue(value), setHeight(px) }`
- 테마: `init.theme = { dark, colors }`, 문서에 `data-theme`와 `--kb-<색 이름>` CSS 변수
