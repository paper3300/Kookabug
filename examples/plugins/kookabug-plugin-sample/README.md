# kookabug-plugin-sample

Kookabug 예제 플러그인이다. 플러그인 프로젝트의 모양을 보여 준다.

- `sample.text.reverse` — 글자를 뒤집는다 (순수 노드)
- `sample.color.pick` — 설정한 색을 출력한다 (설정 `color`, 인스펙터 색 위젯 `sample.color`)
- `sample.window.title` — 창 제목을 읽는다 (`capture` 권한)

UI 확장: `src/kookabug_plugin_sample/ui/index.js`가 색 위젯을 그린다. `ui/kookabug-ui.js`는
`@kookabug/ui-sdk`(`packages/ui-sdk`)의 사본이다 — 위젯은 자기 `ui/` 폴더 파일만 읽을 수 있다.
예제 그래프: `graphs/sample_reverse.graph.json`.

스키마 파일(`src/kookabug_plugin_sample/kookabug.schema.json`)은 커밋하지 않는다. 설치할 때
`kookabug-sdk build`가 만든다.

```powershell
kookabug plugin add git+https://github.com/<you>/kookabug-plugin-sample@v0.1.0
```
