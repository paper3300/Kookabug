# kookabug-sdk · @kookabug/ui-sdk 배포

게시는 사람이 한다 (M6 U6). 이 문서는 판 정책과 명령만 적는다. 이름 선점·계정·토큰은 게시하는 사람의 몫이고
레포·로그에 두지 않는다.

## 판 정책

- `0.x` 동안은 **소판이 호환 경계**다. 플러그인은 `kookabug-sdk>=0.N,<0.N+1`로 의존한다
  (`kookabug-sdk new`가 이 범위를 넣는다. 개발 판이면 하한이 그 판: `>=0.1.0.dev0,<0.2`)
- 앱은 SDK 하나를 동봉하고(`<앱>\plugin-sdk\kookabug_sdk-<판>-py3-none-any.whl`) 플러그인 환경도 그 판을
  쓴다. SDK가 바뀐 앱에서 옛 잠금은 `plugin_env_stale` → `kookabug plugin relock`
- 소판을 올리는 것: 노드 선언·워커 RPC·스키마 머리(`kookabug.nodes/0`)·`schema_digest` 대상이 호환되지 않게
  바뀔 때. 고침판은 호환되는 수정만
- `@kookabug/ui-sdk`는 위젯 메시지 계약(`api: 1`)이 바뀔 때 소판을 올린다. 플러그인은 `ui/` 폴더에
  사본으로 넣으므로(위젯은 그 폴더 파일만 읽는다) 앱과 판을 맞출 필요는 없고 `api`만 맞으면 된다

## 판 올리기

1. `python/kookabug_sdk/pyproject.toml`의 `version`과 `src/kookabug_sdk/__init__.py`의 `__version__`
2. `packages/ui-sdk/package.json`의 `version` (바뀌었으면). 사본(`examples/plugins/*/src/*/ui/kookabug-ui.js`,
   `python/kookabug_sdk/src/kookabug_sdk/templates/plugin/ui/kookabug-ui.js`, `fixtures/plugins/*/src/*/ui/`)은
   `packages/ui-sdk/index.js`와 같아야 한다 (검사 `test_new.py`)
3. 검사: `uv run pytest python/kookabug_sdk -m "packaging or not packaging" --basetemp=<레포 밖>`

## 만들기·게시 (사람)

```powershell
# PyPI: wheel·sdist (dist는 레포 밖에)
uv build python/kookabug_sdk --out-dir $env:TEMP\kookabug-sdk-dist
uv publish $env:TEMP\kookabug-sdk-dist\*            # 토큰: UV_PUBLISH_TOKEN 또는 대화형

# npm
cd packages/ui-sdk
npm pack --dry-run                                   # 들어갈 파일 확인: index.js·index.d.ts·README.md·LICENSE
npm publish --access public
```

- 게시 전에 TestPyPI(`uv publish --publish-url https://test.pypi.org/legacy/`)로 한 번 확인한다
- 게시한 판은 지우거나 덮어쓸 수 없다. 잘못 올렸으면 다음 고침판으로
- 라이선스: 두 SDK 모두 MIT (본체는 Apache-2.0)
