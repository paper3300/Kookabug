# kookabug-plugin-sample

Kookabug 예제 플러그인이다. 플러그인 프로젝트의 모양을 보여 준다.

- `sample.text.reverse` — 글자를 뒤집는다 (순수 노드)
- `sample.color.pick` — 설정한 색을 출력한다 (설정 `color`)
- `sample.window.title` — 창 제목을 읽는다 (`capture` 권한)

스키마 파일(`src/kookabug_plugin_sample/kookabug.schema.json`)은 커밋하지 않는다. 설치할 때
`kookabug-sdk build`가 만든다.

```powershell
kookabug plugin add git+https://github.com/<you>/kookabug-plugin-sample@v0.1.0
```
