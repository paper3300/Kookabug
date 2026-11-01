# 그래프 JSON 스키마 v0 (초안)

- 작성일: 2026-10-29
- 상태: **v0.3 확정**. Codex(GPT-6-Astra) 리뷰 두 차례 반영 → 맨 아래 "리뷰 반영"
- 근거: [[결정 현황]] (그래프 JSON, 노드 결과, 서브그래프 상세)
- 예시 게임: 가상의 "SampleRPG"

---

## 원칙

- 한 파일에 **로직**과 **레이아웃** 블록을 분리한다
- 노드 ID는 **만들 때 정하고 다시 바꾸지 않는다**. 편집기는 `n_` + 짧은 무작위 문자열로 만들고, Agent는 만들 때 읽기 쉬운 ID를 줄 수 있다. 표시 이름은 `title`로만 바꾼다 (실행 기록·브레이크포인트가 ID를 참조하므로)
- 모든 객체의 **키를 정렬**해서 저장한다 (diff 잡음 제거). 아래 예시도 키를 정렬했다. 순서가 의미 있는 값은 배열로 쓴다
- **저장 형식**(canonical, `kookabug_core.canonical`): Kookabug가 파일을 새로 쓰거나 편집한 뒤 저장할 때의 출력 규칙이다. 같은 값이면 같은 바이트가 나온다. 아래 예시도 이 형식이다
  - 키 정렬(UTF-16 코드 단위 순, JavaScript 기본 정렬과 같음), 2칸 들여쓰기, 파일 끝 줄바꿈(LF)
  - 객체는 항상 펼친다(빈 객체만 `{}`). 배열은 원소가 모두 스칼라이고 그 줄이 100자 안이면 `[1, 2]`처럼 한 줄, 아니면 펼친다. 값 하나를 고쳐도 다른 줄이 바뀌지 않게 하려는 것이다
  - 숫자는 JavaScript `JSON.stringify`와 같은 표기(`1.0`은 `1`, `1e-7`). 단, 2^53보다 큰 정수 값의 실수는 지수 표기(`1e+20`)로 쓴다 (아래 정수 범위)
- **원문 보존**: 의미(값)가 바뀌지 않은 저장은 **원문 바이트를 그대로 둔다**(다시 쓰지 않는다). 다른 도구로 만든 비canonical 파일은 처음 편집해 저장할 때 파일 전체를 canonical로 바꾼다
  - 편집기는 파일을 **바이트로** 읽는다(줄바꿈 변환 없음). revision은 그 바이트의 sha256이다
  - 쓸 바이트가 **지금 디스크 바이트**와 같으면 쓰지 않는다(mtime도 그대로). 열 때의 원문이 아니라 지금 디스크와 비교하므로, 밖에서 바뀐 파일을 내 버전으로 덮어쓰는 저장은 값이 원문과 같아도 쓴다
  - BOM으로 시작하는 파일은 읽기 오류다(실행 로더도 읽지 못한다). 저장은 BOM 없는 UTF-8이다
- **정수 범위**: 그래프·target·워크스페이스 파일의 정수는 ±(2^53-1) 안이어야 한다. 넘으면 형식 검사 오류(`number_out_of_range`). JavaScript(에디터)에서 값이 조용히 바뀌는 것을 막는다. 더 큰 수(ID 등)는 문자열로 쓴다. 유한한 실수는 제한하지 않는다
- **비유한 값**: NaN·Infinity는 JSON 값이 아니다. 파일을 읽을 때 `NaN`·`Infinity` 토큰과 float 범위를 넘는 수(`1e400`)는 읽기 오류다. 프로그램(에디터·에이전트)이 직접 넘긴 값에 NaN·±Infinity가 있으면 형식 검사 오류(`number_not_finite`)이고, 저장(canonical)도 거부한다
- 그래프에 `plugins`(플러그인 버전)와 노드마다 `version`(노드 타입 버전)을 기록한다
- 테스트와 서브그래프는 **같은 형식**이고 `kind`만 다르다

## 예시 파일 구성

```
workspace/
├─ subgraphs/enter_world.graph.json   서브그래프: 게임시작 → 로그인 → 월드 접속
├─ tests/inventory_open.graph.json    테스트: 월드 접속 후 인벤토리 열기 확인
├─ targets/                            찾기 대상 (이미지 + 임계값 + 검색 범위 + 클릭 지점)
│  ├─ title/start_button.target.json
│  ├─ title/start_button.png
│  └─ ...
└─ screens/lobby.screen.json          화면 판정 조건 (출구의 screen이 가리킨다)
```

폴더 구조는 열린 질문(워크스페이스 구조)에서 따로 정한다. 여기서는 예시를 위한 임시 구조다.

---

## 1. 서브그래프: `subgraphs/enter_world.graph.json`

흐름: 게임 실행 → 타이틀 대기 → 시작 클릭 → (점검 팝업 / 로그인 창) → 계정 입력 → 로그인 → (로그인 오류 / 로비) → 서버 선택 → 월드 진입 대기

```json
{
  "format": "kookabug.graph/0",
  "interface": {
    "exits": {
      "login_failed": {
        "kind": "fail",
        "screen": "login_error"
      },
      "maintenance": {
        "kind": "fail",
        "screen": "maintenance"
      },
      "success": {
        "kind": "ok",
        "screen": "world_field"
      }
    },
    "inputs": {
      "account": {
        "type": "string"
      },
      "password": {
        "type": "secret"
      },
      "server": {
        "default": "Server 1",
        "type": "string"
      }
    },
    "outputs": {
      "message": {
        "nullable": true,
        "type": "string|secret"
      }
    }
  },
  "kind": "subgraph",
  "layout": {
    "collapsed": {
      "grp_login": {
        "nodes": ["n_click_login", "n_type_account", "n_type_password"],
        "title": "계정 입력",
        "x": 560,
        "y": 0
      }
    },
    "comments": {
      "c_maint": {
        "rect": [560, 220, 320, 120],
        "text": "점검 중이면 테스트 실패가 아니라 호출한 쪽이 처리하도록 출구를 따로 뺀다"
      }
    },
    "nodes": {
      "n_click_enter": {
        "x": 1680,
        "y": 0
      },
      "n_click_login": {
        "x": 840,
        "y": 0
      },
      "n_click_start": {
        "x": 280,
        "y": 0
      },
      "n_entry": {
        "x": -560,
        "y": 0
      },
      "n_exit_login_failed": {
        "x": 1400,
        "y": 200
      },
      "n_exit_maintenance": {
        "x": 840,
        "y": 240
      },
      "n_exit_success": {
        "x": 2240,
        "y": 0
      },
      "n_launch": {
        "x": -280,
        "y": 0
      },
      "n_read_error": {
        "x": 1120,
        "y": 200
      },
      "n_select_server": {
        "x": 1400,
        "y": 0
      },
      "n_type_account": {
        "x": 560,
        "y": -120
      },
      "n_type_password": {
        "x": 700,
        "y": -120
      },
      "n_wait_lobby": {
        "x": 1120,
        "y": 0
      },
      "n_wait_login": {
        "x": 560,
        "y": 120
      },
      "n_wait_title": {
        "x": 0,
        "y": 0
      },
      "n_wait_world": {
        "x": 1960,
        "y": 0
      }
    }
  },
  "meta": {
    "description": "게임을 실행해 로그인하고 지정한 서버의 월드 필드까지 들어간다",
    "tags": ["login", "setup"],
    "title": "월드 접속"
  },
  "nodes": {
    "n_click_enter": {
      "in": {
        "target": {
          "$target": "targets/lobby/enter_world_button.target.json"
        }
      },
      "next": {
        "done": "n_wait_world"
      },
      "title": "월드 입장 클릭",
      "type": "core.image.click",
      "version": 1
    },
    "n_click_login": {
      "in": {
        "target": {
          "$target": "targets/login/login_button.target.json"
        }
      },
      "next": {
        "done": "n_wait_lobby"
      },
      "title": "로그인 버튼 클릭",
      "type": "core.image.click",
      "version": 1
    },
    "n_click_start": {
      "in": {
        "match": {
          "$link": "n_wait_title.match"
        }
      },
      "next": {
        "done": "n_wait_login"
      },
      "title": "시작 버튼 클릭",
      "type": "core.input.click",
      "version": 1
    },
    "n_entry": {
      "next": {
        "start": "n_launch"
      },
      "title": "입력",
      "type": "core.graph.entry",
      "version": 1
    },
    "n_exit_login_failed": {
      "config": {
        "exit": "login_failed"
      },
      "in": {
        "message": {
          "$link": "n_read_error.text"
        }
      },
      "title": "로그인 실패",
      "type": "core.graph.exit",
      "version": 1
    },
    "n_exit_maintenance": {
      "config": {
        "exit": "maintenance"
      },
      "title": "점검 중",
      "type": "core.graph.exit",
      "version": 1
    },
    "n_exit_success": {
      "config": {
        "exit": "success"
      },
      "title": "성공",
      "type": "core.graph.exit",
      "version": 1
    },
    "n_launch": {
      "in": {
        "path": {
          "$setting": "game.executable"
        },
        "timeout_ms": 30000,
        "window_title": "SampleRPG"
      },
      "next": {
        "attached": "n_wait_title"
      },
      "title": "게임 실행",
      "type": "core.app.launch",
      "version": 1
    },
    "n_read_error": {
      "in": {
        "region": {
          "$target": "targets/login/error_text.target.json"
        }
      },
      "next": {
        "done": "n_exit_login_failed"
      },
      "title": "오류 문구 읽기",
      "type": "core.ocr.read",
      "version": 1
    },
    "n_select_server": {
      "in": {
        "region": {
          "$target": "targets/lobby/server_list.target.json"
        },
        "text": {
          "$link": "n_entry.server"
        }
      },
      "next": {
        "done": "n_click_enter"
      },
      "title": "서버 선택",
      "type": "core.ocr.click_text",
      "version": 1
    },
    "n_type_account": {
      "in": {
        "clear": true,
        "target": {
          "$target": "targets/login/account_field.target.json"
        },
        "text": {
          "$link": "n_entry.account"
        }
      },
      "next": {
        "done": "n_type_password"
      },
      "title": "계정 입력",
      "type": "core.input.type_text",
      "version": 1
    },
    "n_type_password": {
      "in": {
        "clear": true,
        "target": {
          "$target": "targets/login/password_field.target.json"
        },
        "text": {
          "$link": "n_entry.password"
        }
      },
      "next": {
        "done": "n_click_login"
      },
      "title": "비밀번호 입력",
      "type": "core.input.type_text",
      "version": 1
    },
    "n_wait_lobby": {
      "config": {
        "exits": ["error", "lobby"]
      },
      "in": {
        "targets": {
          "error": {
            "$target": "targets/login/error_popup.target.json"
          },
          "lobby": {
            "$target": "targets/lobby/server_list.target.json"
          }
        },
        "timeout_ms": 20000
      },
      "next": {
        "error": "n_read_error",
        "lobby": "n_select_server"
      },
      "title": "로그인 오류 또는 로비 대기",
      "type": "core.image.wait_any",
      "version": 1
    },
    "n_wait_login": {
      "config": {
        "exits": ["maintenance", "login"]
      },
      "in": {
        "targets": {
          "login": {
            "$target": "targets/login/account_field.target.json"
          },
          "maintenance": {
            "$target": "targets/title/maintenance_popup.target.json"
          }
        },
        "timeout_ms": 15000
      },
      "next": {
        "login": "n_type_account",
        "maintenance": "n_exit_maintenance"
      },
      "title": "점검 또는 로그인 창 대기",
      "type": "core.image.wait_any",
      "version": 1
    },
    "n_wait_title": {
      "in": {
        "target": {
          "$target": "targets/title/start_button.target.json"
        },
        "timeout_ms": 60000
      },
      "next": {
        "found": "n_click_start"
      },
      "title": "타이틀 대기",
      "type": "core.image.wait",
      "version": 1
    },
    "n_wait_world": {
      "in": {
        "target": {
          "$target": "targets/world/minimap.target.json"
        },
        "timeout_ms": 120000
      },
      "next": {
        "found": "n_exit_success"
      },
      "title": "월드 진입 대기",
      "type": "core.image.wait",
      "version": 1
    }
  },
  "plugins": {
    "core": "0.1.0"
  }
}
```

### 읽는 법

**연결**
- **exec 연결은 출력 쪽 `next`에** 적는다. `"next": { "found": "n_click_start" }` = `found` 출구가 `n_click_start`로 간다
- **data 연결은 입력 쪽 `in`에** 적는다. `{ "$link": "n_wait_title.match" }` = 그 노드의 `match` 출력값
- 그래서 별도의 `edges` 배열이 없다. exec 출구 하나는 한 곳으로만, data 입력 하나는 한 곳에서만 오기 때문에 연결마다 기록이 딱 한 번 생긴다
- `$link`는 노드를 실행시키지 않는다. **현재 호출 프레임에서 이번 경로에 이미 만들어진 출력**만 읽는다. 건너뛴 분기의 출력이나 지난 반복의 값을 읽으려 하면 오류다

**`in`과 `config`**
- `in`은 핀이다. 상수를 직접 넣거나 다른 노드와 연결한다
- `config`는 연결할 수 없는 노드 설정이고, 노드 모양을 바꿀 수 있다. 예: `wait_any`의 `config.exits` 배열이 exec 출구 이름과 **우선순위**가 된다. 각 출구의 찾기 대상 값은 `in.targets`로 받으므로 다른 노드에서 연결할 수도 있다
- `wait_any`에서 여러 대상이 동시에 보이면 `config.exits` 배열의 앞쪽이 이긴다. 예시에서는 점검 팝업이 로그인 창 위에 뜰 수 있으므로 `maintenance`를 앞에 둔다

**특수 값**

`in` 안에서 `$`로 시작하는 키 **하나만** 가진 객체가 특수 값이다. 아래 다섯 개만 허용하고(닫힌 목록), 모르는 태그나 없는 참조는 실행 전 검증 오류다.

| 특수 값 | 뜻 |
|---|---|
| `{ "$link": "노드ID.출력" }` | 다른 노드의 출력과 연결 |
| `{ "$target": "경로" }` | 찾기 대상 파일 |
| `{ "$setting": "키" }` | 워크스페이스 설정값 (사람마다 다른 경로 등) |
| `{ "$secret": "키" }` | 비밀 저장소의 값 |
| `{ "$literal": 값 }` | 이스케이프. 안의 값을 해석하지 않고 그대로 쓴다 (`$`로 시작하는 키를 가진 일반 객체를 넣을 때) |

- 특수 값은 핀 값의 **안쪽 어디에나** 올 수 있다. 배열 원소나 일반 객체의 값도 된다 (예: `n_wait_lobby`의 `in.targets.error`가 `$target`). `$literal` 안은 해석하지 않는다
- `$`로 시작하는 키와 다른 키가 섞인 객체(`{ "$link": "a.b", "x": 1 }`)는 일반 객체가 아니라 오류다. `$`로 시작하는 키를 가진 일반 객체는 `$literal`로 감싸서만 쓴다

**상수**

- 스칼라·목록·객체 상수는 핀 타입 그대로 쓴다 (`"timeout_ms": 30000`, `"args": ["-m", "game"]`)
- 점·사각형은 배열 상수다. 좌표는 대상 창 **클라이언트 영역의 물리 픽셀**(정수)이다
  - `point`: `[x, y]`. 예: `"point": [512, 412]`
  - `rect`: `[x, y, w, h]`, 너비·높이 1 이상. 예: OCR 영역 `"region": [262, 190, 500, 170]`
- 유니온 핀의 그 항에도 같다 (`core.input.drag`의 `start`(`match|point`)에 `[x, y]`, `core.ocr.read`의 `region`(`target|rect`)에 `[x, y, w, h]`). 목록·사전 안쪽(`list[point]`)도 같다. 유니온이면 값이 실제로 맞는 항으로 바꾼다(`list[string]|list[point]`에 `[[1, 2]]`면 점 목록)
- 원소에 특수 값을 써도 된다: `"point": [{ "$link": "n_get.value" }, 412]`. 실행 전 검증은 원소 개수와 연결 타입(정수에 연결할 수 있는가)만 보고, 연결로 온 값이 정수인지·너비·높이가 1 이상인지는 실행기가 입력을 계산한 뒤 다시 본다(틀리면 `error`/`type_mismatch`)
- 실행 전 검증이 모양을 본다. 틀리면 `type_mismatch`(메시지에 모양). 실행기는 입력을 계산할 때 핀 타입대로 `Point`·`Rect`로 바꿔 노드에 준다 — 노드는 상수 모양을 따로 바꾸지 않는다. 다른 노드 출력으로 연결한 `Point`·`Rect`는 그대로다
- `match`는 상수로 쓸 수 없다(찾기 결과는 연결로만 온다). 그 밖의 구조 타입(`image`·`window` 등)도 연결로 받는 값이다
- **픽셀 상수는 창 크기·DPI에 따라 바뀌지 않는다.** 그 좌표를 적은 해상도에서만 같은 곳을 가리킨다. 그래서 픽셀 상수를 쓰는 그래프는 앞에서 `core.window.set_size`로 클라이언트 크기를 고정하거나, 해상도마다 영역을 다시 잡는다. 화면 비율에 따르는 영역이 필요하면 찾기 대상(`$target`)으로 쓴다 — target의 `search.region`(정규화 좌표, 4장)은 검색 범위이고, 노드는 찾은 상자를 영역으로 쓴다. 정규화 사각형 상수는 M1에 없다
- 영역이 지금 화면과 하나도 겹치지 않으면(창이 작아진 뒤 포함) 그 노드는 `error`다(지금 클라이언트 크기와 요청 영역을 메시지에 적는다). 겹치지 않는 영역을 "변화 없음"·"글자 없음"으로 보지 않는다

**비밀값**
- `secret` 타입 값은 연결을 따라가도 비밀 속성을 유지한다. `n_entry.password → n_type_password.text`로 넘어가도 실행 기록·로그·노드 결과에는 가려서 남긴다
- `secret` 값은 `secret`을 포함한 핀에만 연결할 수 있다. 그래서 `type_text.text`처럼 평문과 비밀을 다 받는 핀은 유니온 `string|secret`으로 선언한다. `string`만 받는 핀에 연결하면 실행 전 검증 오류다. `any` 핀(`var.set.value`, `text.format.values`의 값 등)은 비밀값도 받는다
- 비밀 입력에서 만든 순수 노드 출력도 비밀이다. 예: `core.text.format`의 값 중 하나라도 비밀이면 결과 `text`도 비밀
- `any` 출력(`var.get.value` 등)을 거치면 실행 전 검증이 비밀값을 알아볼 수 없다. 그래서 실행기는 노드 입력을 계산할 때 값을 핀 타입과 다시 대조하고, 비밀값이 `string`만 받는 핀에 닿으면 `error`로 멈춘다
- 스크린샷·영상·OCR 결과에 화면으로 찍힌 비밀은 이 규칙으로 막을 수 없다. 기록 정책에서 따로 다룬다

**현재 대상 창**
- `core.app.launch`가 그 호출 프레임의 **현재 대상 창**을 정하고, 이후 노드는 그 창을 쓴다. 서브그래프는 호출한 쪽의 현재 대상 창을 이어받는다 (변수는 이어받지 않음)
- 노드에 `window` 입력을 주면 **그 노드만** 다른 창을 쓴다. 호출한 쪽의 현재 대상 창을 바꾸려면 명시적인 노드(`core.window.set_current`)를 쓴다
- 캡처·매칭 결과에는 창 식별자와 좌표 변환 정보가 붙고, 입력 노드는 입력 직전에 그 창이 아직 유효한지 확인한다

**접기**
- `grp_login`은 `layout` 블록에만 있다. 로직에는 영향이 없다. 접힌 노드도 펼쳤을 때를 위해 좌표를 가진다

**화면 선언**
- `interface.exits`의 `screen`은 **그 출구로 나갔을 때 도착하는 화면**이다. 화면 지도에 출구별 전이로 기록하는 데 쓴다
- 이 값으로 실행을 건너뛰지 않는다 (ensure 없음. 아래 "리뷰 반영" 참고)

---

## 2. 출구와 테스트 판정

**출구 종류**
- 노드 스키마와 `interface.exits`가 출구마다 `ok` / `fail`을 정한다
- `error`(노드 고장)와 취소는 출구로 나가지 않는다. 호출 스택을 따라 위로 전파하고, 테스트는 `error`로 끝난다. try/catch 노드는 이후 버전에서 다룬다
- 테스트 전체 기한(실행 옵션, 기본 30분)을 넘는 것도 `error`(`deadline_exceeded`)다. 노드 타임아웃처럼 fail 출구로 나가지 않는다. 기한은 무한 반복·멈춘 실행을 끊는 장치이지 테스트 결과가 아니다

**fail 출구**
- 연결 안 된 `fail` 출구 → **그 노드에서 처리되지 않은 실패**. 예: `n_wait_title`의 `timeout`은 연결이 없으므로 타이틀이 안 뜨면 여기서 실패
- 연결된 `fail` 출구 → **분기**일 뿐 **복구**가 아니다. 그 노드의 결과는 `fail`로 남는다. 그 경로가 아래 중 하나에 도달해야 처리된 것으로 본다
  - 테스트: `core.test.pass` 또는 `core.test.skip` 종료 노드
  - 서브그래프: 공개 exit(`core.graph.exit`). 판단은 호출한 쪽으로 넘어간다
- fail 분기에서 스크린샷만 찍고 끝나면 처리되지 않은 실패다
- 예외: 출구 없이 처리되지 않은 fail이 되는 경우가 있다. 입력 직전 재검증 실패(`stale_observation`, 6장)가 그렇다. `exit: null`과 사유를 기록하고 호출 스택을 따라 전파한다

**서브그래프 안쪽 실패**
- 서브그래프 안에서 처리되지 않은 실패는 공개 출구로 나가지 않고, 호출 스택을 따라 테스트까지 올라간다. 실패 위치는 경로(`월드 접속 > 타이틀 대기`)로 표시한다
- 호출한 쪽에서 잡고 싶은 실패는 서브그래프 작성자가 공개 exit로 만든다 (예: `login_failed`)
- 공개 exit로 나간 실패는 안쪽 기록을 보존하되, 같은 실패를 따로 한 번 더 전파하지 않는다
- 종료 노드(`core.test.pass` / `skip` / `fail`)는 **테스트에서만** 쓴다. 서브그래프 안에 두면 검증 오류다. 서브그래프의 끝은 항상 공개 exit다 (함수 반환과 테스트 종료를 구분)

**테스트 판정 순서**

| 순서 | 조건 | 판정 |
|---|---|---|
| 1 | `error`나 취소가 있었다 | `error`. 무엇으로도 덮지 않는다 |
| 2 | 처리되지 않은 `fail`이 있었다 | `fail` |
| 3 | `core.test.fail` 종료 노드에 도달 | `fail` |
| 4 | `core.test.skip` 종료 노드에 도달 | `skipped` |
| 5 | 검증 노드 또는 `core.test.pass`가 하나 이상 성공 | `pass` |
| 6 | 그 외 (검증 없이 끝남) | `fail` ("검증 없음") |

**검증 노드** = 노드 스키마에 `assertion: true` 표시가 있는 노드 (SDK `@node(assertion=True)`). `core.assert.*`가 모두 그렇고, 플러그인 검증 노드도 같은 표시로 판정 5행에 들어간다 → [[Python 노드 SDK v0]]

**실행 전 검증**
- 테스트에서 연결 안 된 `ok` 출구로 끝나는 노드는 경고한다. 단, 그 노드가 검증 노드(`assertion` 표시)면 경고하지 않는다 (`검증 → 클릭 → 끝`은 경고)
- `core.graph.entry`는 정확히 하나. 서브그래프의 모든 경로는 공개 exit 또는 처리되지 않은 실패로 끝나야 한다. 그래서 서브그래프에서 연결 안 된 `ok` 출구는 경고가 아니라 **오류**다 (반복 본문 끝은 반복 노드로 돌아가므로 제외, 7장 "반복")
- 테스트에 `core.graph.exit`를 두면 오류다 (테스트는 `core.test.*`로 끝낸다). 서브그래프에 `core.test.*`를 두는 것도 오류다
- 반복에는 횟수 한도가 필요하다. 테스트 전체에도 기한이 있다 (노드별 타임아웃과 별개)

---

## 3. 테스트: `tests/inventory_open.graph.json`

```json
{
  "format": "kookabug.graph/0",
  "kind": "test",
  "layout": {
    "nodes": {
      "n_check_inventory": {
        "x": 560,
        "y": 0
      },
      "n_enter_world": {
        "x": 0,
        "y": 0
      },
      "n_entry": {
        "x": -280,
        "y": 0
      },
      "n_press_i": {
        "x": 280,
        "y": 0
      },
      "n_skip_maintenance": {
        "x": 280,
        "y": 160
      }
    }
  },
  "meta": {
    "description": "월드에 들어간 뒤 I 키로 인벤토리 창이 열리는지 확인한다",
    "tags": ["inventory", "smoke"],
    "title": "인벤토리 열기"
  },
  "nodes": {
    "n_check_inventory": {
      "in": {
        "target": {
          "$target": "targets/inventory/window_title.target.json"
        },
        "timeout_ms": 5000
      },
      "title": "인벤토리 창 확인",
      "type": "core.assert.visible",
      "version": 1
    },
    "n_enter_world": {
      "config": {
        "graph": "subgraphs/enter_world.graph.json"
      },
      "in": {
        "account": "qa_tester_01",
        "password": {
          "$secret": "accounts.qa_tester_01"
        },
        "server": "Server 1"
      },
      "next": {
        "maintenance": "n_skip_maintenance",
        "success": "n_press_i"
      },
      "title": "월드 접속",
      "type": "core.graph.call",
      "version": 1
    },
    "n_entry": {
      "next": {
        "start": "n_enter_world"
      },
      "title": "시작",
      "type": "core.graph.entry",
      "version": 1
    },
    "n_press_i": {
      "in": {
        "keys": "I"
      },
      "next": {
        "done": "n_check_inventory"
      },
      "title": "I 키",
      "type": "core.input.key",
      "version": 1
    },
    "n_skip_maintenance": {
      "in": {
        "reason": "서버 점검 중"
      },
      "title": "점검이면 건너뜀",
      "type": "core.test.skip",
      "version": 1
    }
  },
  "plugins": {
    "core": "0.1.0"
  }
}
```

- 서브그래프 호출은 `core.graph.call` 노드 하나다. `config.graph`의 경로로 **참조**한다. 서브그래프 파일을 고치면 **다음 실행부터** 이 테스트에도 반영된다
- 호출 노드의 핀은 서브그래프 `interface`에서 만들어진다. `inputs` → data 입력, `exits` → exec 출구, `outputs` → data 출력
- 호출한 쪽은 **실제로 나간 출구**에서 보장되는 출력만 읽는다. `message`는 `nullable`이므로 `success`로 나가면 `null`이다
  - 서브그래프의 **모든** `core.graph.exit` 노드(`fail` 종류 출구로 나가는 것 포함)는 `nullable`이 아닌 출력을 전부 줘야 한다. 빠뜨리면 실행 전 검증 오류다. 출구별로 non-nullable 출력을 생략하는 선언은 없다
  - `nullable` 출력은 exit 노드가 주지 않으면 `null`로 채운다. 그래서 호출 노드의 출력은 **모든 출구에서 주어진 것**으로 본다 (값이 `null`일 수는 있다)
- `login_failed`는 연결하지 않았다 → 로그인이 실패하면 `n_enter_world`에서 처리되지 않은 실패 → 테스트 `fail` (판정 순서 2)
- `maintenance`는 skip 종료 노드로 연결했다 → 테스트 `skipped` (판정 순서 4). 점검 때문에 테스트가 빨갛게 되지 않는다
- `n_check_inventory`(검증 노드)가 성공하고 끝나면 → 테스트 `pass` (판정 순서 5)

---

## 4. 찾기 대상: `targets/title/start_button.target.json`

```json
{
  "click": {
    "anchor": "center",
    "offset": [0, 0]
  },
  "format": "kookabug.target/0",
  "image": "start_button.png",
  "match": {
    "color_tolerance": 40,
    "methods": ["template_multiscale", "template"],
    "rgb": true,
    "threshold": 0.85
  },
  "recorded": {
    "client_size": [1920, 1080],
    "dpi": 96
  },
  "search": {
    "region": [0.35, 0.6, 0.3, 0.25]
  }
}
```

- 이미지, 임계값, 클릭 지점, 녹화 당시 해상도·DPI를 한 객체에 담는다 (SikuliX Pattern, Airtest Template)
- `image`는 이 target 파일 기준 상대 경로다
- `search.region`은 클라이언트 영역 기준 정규화 좌표 `[x, y, w, h]`다
- `anchor`는 9분할 클릭 지점(`top_left` … `center` … `bottom_right`)이다
- `methods`는 앞에서부터 시도한다. 각 방법은 `threshold`를 넘어야 성공이다
  - `template`은 배율 1.0, `template_multiscale`은 기대 배율 × `1.0, 0.95, 1.05, 0.9, 1.1, 0.85, 1.15, 0.8, 1.2` 순서로 본다. 기대 배율은 지금 클라이언트 높이 / `recorded.client_size`의 높이, 그것이 없으면 지금 DPI / `recorded.dpi`, 둘 다 없으면 1.0이다. 처음으로 `threshold`를 넘는 방법·배율에서 끝난다
  - 점수는 정규화 상관계수(`TM_CCOEFF_NORMED`)다. `rgb: true`(기본)면 컬러로, `false`면 회색조로 비교한다
  - `rgb: true`면 색도 확인한다: 찾은 자리와 이미지의 채널별 평균 차이가 `color_tolerance`(기본 40, 0~255)를 넘으면 그 자리는 실패다. 모양은 같고 색만 다른 것(회색으로 바뀐 비활성 버튼 등)을 걸러 낸다
  - 기본값: `threshold` 0.85, `methods` `["template_multiscale", "template"]`, `rgb` true
- 이미지의 알파가 0인 픽셀은 비교에서 뺀다(마스크). 버튼 모서리 밖 배경처럼 화면마다 다른 부분을 지운 PNG로 쓴다
- 클릭 지점은 찾은 상자(배율을 곱한 크기)의 `anchor` 지점 + `offset × 찾은 배율`이다. 오른쪽·아래 끝은 상자 안 마지막 픽셀이다
- 여러 그래프가 같은 대상을 쓰므로 파일로 분리한다 (UiPath Object Repository). 사용처 추적은 target 파일과 PNG까지 포함한다
- 확인 도구: `kookabug target test <target.json> (--window 제목 | --image PNG)`가 찾은 상자·점수·배율·클릭 지점을 그린 미리보기 PNG를 만든다

#### 편집기 저장 (M2)

target 편집기(daemon `target.save`)는 정지 화면에서 자른 영역으로 target을 저장한다. 실패한 저장은 기존 target을 바꾸지 않고, 사용자가 넣은 PNG는 어떤 경우에도 지우지 않는다.

- **revision**: `sha256(JSON 바이트) + ":" + sha256(image가 가리키는 파일 바이트)`. 이미지가 없으면 `missing`이다. 이미지만 밖에서 바뀌어도 revision이 달라지고, 기존 파일 저장은 이 revision이 맞아야 한다(새 파일은 없어야 한다)
- **채우는 값**: `image`는 새로 고른 이름, `recorded.client_size`·`recorded.dpi`는 그 정지 화면(창 캡처면 그 창, PNG면 이미지 크기·96). `search.region`은 소수 6자리 정규화 좌표이고, 그 클라이언트 크기에서 픽셀 → 정규화 → 픽셀이 같은 사각형이 되는 값을 쓴다(반올림이 어긋나면 바깥 방향부터 한 단계씩 옮긴다)
- **이미지 공개**: 있는 PNG는 제자리에서 바꾸지 않는다. target 옆 `<줄기>.png` → `<줄기>-<sha256 앞 8자>.png` → 16자 → 64자 순으로 **배타적 생성**(이미 있으면 실패)을 시도한다. 이미 있는 파일이 같은 바이트면 재사용한다(쓰지 않고, 에디터 소유도 아니다)
- **커밋**: target JSON 한 번의 쓰기다(기존 파일이면 원문 보존, 같은 바이트면 쓰지 않음). 쓰기 직전에 revision을 다시 잰다. 그 사이 밖에서 바뀌었으면 이 저장이 직접 만든 PNG 하나만, 지금도 같은 바이트이고 어떤 `*.target.json`도 가리키지 않을 때 지운다
- **에디터 소유 기록** `.kookabug/editor-images.json`([[워크스페이스 구조]]): 편집기가 배타적 생성으로 만든 이미지만 적는다. 저장 뒤 옛 이미지는 이 기록에 있고, 지금 바이트가 기록과 같고, 어떤 `*.target.json`도 가리키지 않을 때만 지운다. 기록을 읽을 수 없으면 정리하지 않는다
- "어떤 `*.target.json`도 가리키지 않음"은 워크스페이스의 target 파일을 **모두** 읽었을 때만 인정한다. 하나라도 읽지 못하면(잠김·권한·JSON이 아님) 되돌리기·정리 모두 이미지를 지우지 않고, 저장 결과에 경고를 담는다. 정리는 daemon의 target 저장 잠금 안에서 하고, 지울 이미지마다 **지우기 직전에** 참조를 다시 읽는다(다시 읽지 못하면 그 이미지와 그 뒤는 지우지 않는다)
- 한계: daemon 밖 프로세스(사람·다른 도구)가 참조를 다시 읽은 바로 그 순간과 지우는 순간 사이에 target 파일을 고치는 경우는 막을 수 없다. 그 경우 지워지는 것은 에디터가 만들고 바이트가 그대로인 이미지뿐이다
- 커밋 뒤의 정리는 저장을 실패로 바꾸지 않는다(실패는 경고). 실패할 수 있는 검사는 모두 쓰기 전에 끝낸다
- 저장 도중 프로세스가 죽으면 새 PNG 하나(고아)만 남는다. 기록되기 전에 죽은 고아는 자동으로 지우지 않는다
- **바로 매칭**: 영역을 고른 저장은 쓰기 전에 저장할 사양과 PNG 바이트 그대로 그 정지 화면에서 찾는다. 찾지 못하면(검색 범위 밖·임계값 등) 또는 결과를 나타낼 수 없으면(정수 범위를 넘는 클릭 지점 등) 아무것도 쓰지 않고 거부한다. 저장 결과는 그 찾은 결과다(저장한 파일을 다시 읽어 찾은 것과 같다). 같은 무늬가 화면에 한 번이면 찾은 상자가 자른 영역(배율 1.0)이다
- **영역 없이 저장**(임계값·클릭 지점 등 사양만 고칠 때, 기존 파일만): 이미지를 새로 만들거나 지우지 않고 지금 `image`·`recorded`를 그대로 둔 채 JSON만 저장한다. 검색 범위는 `recorded.client_size` 기준으로 위와 같이 맞춘다. 지금 이미지가 없거나 이미지가 아니면 저장하지 않는다(영역을 다시 고른다). 찾을 정지 화면이 없으므로 바로 매칭 결과는 없다

### 화면 판정 파일: `screens/lobby.screen.json`

```json
{
  "detect": {
    "all": [
      {
        "$target": "targets/lobby/server_list.target.json"
      }
    ],
    "none": [
      {
        "$target": "targets/common/loading.target.json"
      }
    ]
  },
  "format": "kookabug.screen/0",
  "title": "로비"
}
```

- 서브그래프 출구의 `screen`(1장)이 가리키는 화면을 판정하는 조건이다. 화면 ID는 파일 이름 줄기(`lobby`)다
- `screens/` 아래 어디에 둬도 된다. `screens/_explored/`(Agent 탐색 결과, 사람 확인 전)는 보지 않는다
- `detect.all`의 대상이 전부 보이고 `detect.none`의 대상이 하나도 안 보이면 이 화면이다. 둘 중 적어도 하나는 있어야 한다. 값은 `$target`(워크스페이스 루트 기준)만 쓴다 (화면 지도 단계에서 OCR 조건 등을 더한다)
- 실행 전 검증
  - 출구의 `screen`이 없는 화면 ID면 경고 `screen_unknown`. 화면 지도용 정보라 실행을 막지 않는다
  - 검증하는 그래프(와 그것이 부르는 서브그래프)의 출구가 가리킨 화면 ID의 파일이 둘 이상이면 오류 `screen_ambiguous`. 아무 출구도 가리키지 않는 ID의 중복은 그 그래프의 검증에서 보지 않는다(관계없는 그래프 검증이 실패하지 않게). `kookabug screen test <화면 ID>`는 그 ID가 중복이면 오류로 끝난다
  - 화면 파일 형식이 틀렸거나 그 target을 쓸 수 없으면 경고 `screen_invalid`
- 실행 중에는 화면 판정으로 실행 흐름을 바꾸지 않는다. 확인 도구 `kookabug screen test <화면 ID|파일> (--window 제목 | --image PNG)`가 조건별 결과를 보여 준다

---

## 5. 실행 기록

### 실행 폴더

```
runs/2026-10-29T15-02-11_inventory_open_r8k2x7qm/
├─ run.json            run_id, 대상 테스트, 러너·플러그인·의존성 버전, 게임 빌드, 실행 조건, 결과
├─ events.jsonl        시작·종료 이벤트. 실행 중에도 한 줄씩 덧붙인다
├─ input-recovery.json (있을 때만) 이 실행에서 눌렸을 수 있는 키를 누가 뗐는지
├─ snapshot/           실행 시작 때 복사한 그래프·서브그래프·타깃·이미지·화면 정의
├─ steps/              스크린샷 등 artifacts
├─ thumbs/             (M3) 캡처한 스텝의 썸네일 <스텝>.jpg (긴 변 480). 지난 성공과 화면 비교의 근거
├─ video/              (M3) 연속 영상: 조각 seg-NNNN.mp4, 조각 목록 segments.jsonl, 칸 기록 seg-NNNN.frames.jsonl, 마무리 색인 index.json
└─ logs/               러너·워커의 stdout·stderr
```

- 폴더 이름: `<시작 시각 UTC YYYY-MM-DDTHH-MM-SS>_<테스트 그래프 파일 줄기>_<run_id>`. `run_id`는 소문자·숫자 8자이고, 이미 쓰인 ID면 다시 뽑는다
- `run.json`은 원자적 교체로만 쓴다 (`running` → `finished`). 형식은 `packages/schema/run.schema.json`
  - M3부터 더하는 필드(모두 선택, 예전 실행에는 없다): `active_duration_ms`(멈춘 시간을 뺀 경과), `retried_steps`(재시도 끝에 성공한 스텝 수, "불안정" 표시), `observed`(처음 관측한 창의 캡처 방식·클라이언트 크기·DPI), `video`(영상 요약 `{status, reason, kept, deleted, bytes}` — `video/index.json`에서 읽는다). `pause_count`·`paused_ms`·`debug_intervened`는 6장
- `thumbs/<스텝>.jpg`는 이벤트에 적지 않는다. 반복 안 스텝은 첫 회차와 마지막 두 회차만 남기므로 **파일 유무가 기준**이다. 정책으로 막힌 썸네일은 그 스텝 `step.end.omitted`의 `kind: "thumbnail"`
- `video/` (M3): 조각 하나는 한 모드(`on`·`failed_only`)·한 창·한 크기·최대 60초이고 안에 빈 구간이 없다. 쓰는 중에는 `seg-NNNN.part.mp4`다(MP4는 닫을 때 색인을 쓴다)
  - `segments.jsonl`: 녹화 스레드가 닫은 조각(`file`·`mode`·`t0`·`frame_ms`·`frames`·`t_end`·`size`·`window`·`bytes`)이나 비운 구간(`gap`·`t_start`·`t_end`, 이유 `policy_off`·`secret_input`·`paused`·`no_window`·`capture_missed`·`unavailable`·`interrupted`)을 한 줄씩 덧붙인다. 조각은 `t0`부터 `frame_ms`(초당 5장이면 200) 칸마다 한 장을 쓰므로 재생 위치 `k × frame_ms` = 실행 시각 `t0 + k × frame_ms`다
  - `seg-NNNN.frames.jsonl`: 칸마다 쓴 프레임(`slot`·`pixels_at`·`repeat`). 검사·사람 확인용이다
  - `index.json`: 실행 마무리가 **최종 `run.end`** 기준으로 남길 조각·지운 조각과 이유·빈 구간·`status`를 정해 원자적 교체로 공개한다. 없으면 읽는 쪽이 `segments.jsonl`만 보고 보여 준다(읽기는 고치지 않는다)
  - 형식은 `packages/schema/video-index.schema.json`(`index.json`, `segments.jsonl` 줄 `SegmentsLine`, `frames.jsonl` 줄 `FramesLine`)
- **실행 시작 때 고정**: 러너는 시작할 때 테스트가 참조하는 모든 파일을 따라가 `snapshot/`에 복사하고, 실행 내내 그 복사본만 읽는다. 실행 중에 서브그래프나 이미지를 고쳐도 이번 실행에는 섞이지 않는다
  - 따라가는 방법: `kookabug.json`과 테스트 그래프를 복사하고, 스냅샷에서 읽어 새로 보이는 참조(서브그래프·target·target의 이미지·서브그래프 출구가 가리킨 화면 판정 파일과 그 target·이미지)를 복사하기를 더 없을 때까지 되풀이한다. 화면 판정 파일은 ID로 찾으므로 원본의 `screens/`에서 그 ID의 파일을 찾아 복사한다. 파일마다 한 번만 복사하므로 호출 깊이와 상관없이 끝난다. 실행은 마지막으로 읽은 결과를 그대로 쓴다
  - 설정(`$setting`의 `kookabug.json` 기본값·프로필)도 복사한 `kookabug.json`에서 읽는다. `.kookabug/local.json` 값은 원본에서 읽는다
  - 다 따라간 뒤 복사한 원본의 크기·수정 시각을 다시 보고, 복사 도중 바뀐 것이 있으면 스냅샷을 비우고 처음부터 다시 한다. 세 번 다시 해도 바뀌면 `error`(`snapshot_unstable`). 파일 1만 개·합계 1 GiB를 넘으면 `error`(`snapshot_too_large`)
  - 원본에도 없는 참조는 복사하지 않고, 실행 전 검증이 원래 오류(`call_target_missing`·`target_missing`·`target_invalid`)로 보고한다. 호출 깊이 한도는 `call_depth`다
  - `step.end.graph`는 실행 폴더 기준 스냅샷 경로(`snapshot/subgraphs/…`)다
- 비밀값은 복사하지 않는다. 참조 키(`accounts.qa_tester_01`)만 남긴다
- `.kookabug/local.json`은 복사하지 않는다. 실제로 쓴 설정값만 `run.json`의 실행 조건에 남긴다 (비밀값은 키만)
  - 그래프·target의 경로가 개인 폴더 `.kookabug/` 안을 가리키면 복사하지 않고 `error`(`snapshot_private_file`)로 멈춘다. 경로 기준이다: 대소문자를 바꾼 경로, 심볼릭 링크·정션을 거친 경로는 실제 경로로 풀어 막는다. 하드 링크는 대상이 아니다(다른 경로의 일반 파일로 보고 복사한다. 사용자가 자기 작업 폴더에서 일부러 만드는 것이고 보안 경계가 아니다)
- 당시 실행 정의를 재구성할 수는 있지만, 게임 서버 상태까지 되돌릴 수는 없다. "같은 정의로 다시 실행"과 "같은 결과 재현"은 다르다

### `events.jsonl` (일부)

```jsonl
{"attempt": 1, "event": "step.start", "node": "n_enter_world", "parent": null, "path": ["n_enter_world"], "run": "r8k2x7qm", "seq": 4, "step": "s1", "t": "2026-10-29T15:02:12.104Z"}
{"attempt": 1, "event": "step.start", "node": "n_wait_title", "parent": "s1", "path": ["n_enter_world", "n_wait_title"], "run": "r8k2x7qm", "seq": 7, "step": "s2", "t": "2026-10-29T15:02:13.010Z"}
{"artifacts": ["steps/s2_before.png", "steps/s2_after.png"], "attempt": 1, "duration_ms": 8120, "event": "step.end", "exit": "found", "outputs": {"match": {"score": 0.93, "window": "w1", "xywh": [812, 701, 296, 88]}}, "run": "r8k2x7qm", "seq": 8, "status": "success", "step": "s2", "t": "2026-10-29T15:02:21.130Z"}
{"attempt": 1, "duration_ms": 41230, "event": "step.end", "exit": "success", "graph": "snapshot/subgraphs/enter_world.graph.json", "outputs": {"message": null}, "run": "r8k2x7qm", "seq": 31, "status": "success", "step": "s1", "t": "2026-10-29T15:02:53.334Z"}
```

- 한 줄이 이벤트 하나다. UTF-8·LF, 키 정렬. 형식은 `packages/schema/events.schema.json`(이벤트 종류마다 필드를 고정)
- 모든 줄에 붙는 필드
  - `event`: 이벤트 종류
  - `run`: 실행 ID
  - `seq`: 저널 안 순번. 1부터 빈틈 없이 늘어난다. 줄이 빠졌는지를 이것으로 안다
  - `t`: 쓴 시각 (UTC, 밀리초까지, `Z`)
- 이벤트 종류

| `event` | 내용 |
|---|---|
| `run.start` / `run.end` | 실행 시작·결과 (`verdict`, `code`, `reason`, 실패 위치, 누가 마무리했는지 `finalized_by`). M3: `active_duration_ms`·`paused_ms`·`debug_intervened`(6장), 실행 단위로 남기지 않은 기록 `omitted`(`[{kind: "video", reason: "encoder_stuck"}]` — 녹화 스레드가 멈춰 그 실행의 영상을 포기함) |
| `step.start` / `step.end` | 스텝 시작·결과 |
| `attempt.end` | 재시도할 중간 시도의 실패 (6장 "재시도") |
| `log` | 노드·러너 로그 |
| `input.down` / `input.up` / `input.recovered` | 키·버튼 누르기·떼기, 앞 실행에서 눌린 채 남은 키를 뗀 기록 |
| `cancel.requested` | 취소 시작과 사유 (`cancelled`·`deadline_exceeded`·`supervisor_lost`) |
| `control.lost` | 러너와 감독자 사이의 제어 채널이 끊김 (취소는 아님) |
| `debug.pause` / `debug.resume` | 멈춤·재개 (6장). `debug.pause`: `step`(경계 멈춤이면 다음에 시작할 스텝, 폴링 멈춤이면 기다리던 스텝), M3부터 `node`·`graph`(워크스페이스 기준)·`path`, `reason`(`breakpoint`·`step`·`request`), `where`(`boundary`·`poll`). `debug.resume`: M3부터 `mode`(`continue`·`step_over`·`step_into`·`step_out`), `epoch`(재개 뒤 관측 세대), `paused_ms`(이번 멈춤) |
| `worker.start` / `worker.exit` | 플러그인 워커 프로세스 시작·종료. 종료 사유: `shutdown`(정상), `killed_after_grace`(취소 유예 초과로 끝냄), `unexpected`(스스로 죽음), `start_timeout`·`start_failed`·`cancelled`(시작 중 hello 기한 초과·실패·취소) |

- `step.end`의 확정된 노드 결과(`status`, `outputs`, `error`, `artifacts`, `duration_ms`)에 더하는 필드
  - `run`, `step`, `parent`: 실행과 스텝 인스턴스 ID. 같은 노드가 반복·재호출돼도 구별된다
  - `attempt`: 재시도 번호
  - `exit`: 어느 exec 출구로 나갔는지
  - `path`: 호출 경로. 실패 위치를 `월드 접속 > 타이틀 대기`처럼 보여 줄 때 쓴다
  - `graph`: 서브그래프 호출이면 이번 실행에 쓴 스냅샷 파일
  - `omitted`: 정책으로 남기지 않은 증거와 이유 (6장 "화면에 찍힌 비밀값")
  - `active_duration_ms` (M3): 멈춘 시간을 뺀 경과. 그 스텝 구간에 디버거 멈춤이 있었을 때만 쓴다. `duration_ms`는 늘 실제 경과다
  - `evidence` (M3): fail·error·`stale_observation`으로 끝난 스텝의 증거. 그 스텝의 첫 캡처(`first`, `steps/<스텝>_first.png`)·중간 캡처(`mid`)·마지막 캡처(`last`, `_fail`·`_error`)와 각 실제 캡처 시각(`*_at_ms`, 스텝 시작 기준 벽시계 ms), 찾기·대기 노드가 fail 출구로 끝났으면 마지막 찾기의 `target`·`threshold`·상위 후보 3개 `candidates`(`score`·`rect`·`scale`, `rect`는 `_fail` 이미지 좌표)
    - 중간은 근사이고 최선 노력이다. 폴링 스텝은 끝나는 시각을 모르므로 표본 중 (시작 + 끝)/2에 가장 가까운 캡처를 고르고 그 편차를 `mid_offset_ms`에 남긴다. 편차가 경과의 1/4을 넘거나 첫·마지막 말고 표본이 없으면 `mid: null`, `mid_missing: "no_sample_near_mid"`(뷰어는 "중간 장면 없음")
- `step.end`가 없는 스텝은 러너가 중간에 죽은 것이다. 뷰어는 "중단"으로 표시한다
  - 러너가 죽으면 감독자가 러너 종료를 확인한 뒤 기록을 마무리한다: 잘린 끝 줄을 잘라 내고, 눌렸을 수 있는 키를 떼고, `run.end`가 없으면 `run.end`(`error`/`runner_died`, `finalized_by: supervisor`)를 덧붙이고, `run.json`을 `run.end`에서 다시 만든다. 이미 있는 `run.end`는 덮어쓰지 않는다. 열린 스텝에는 `step.end`를 쓰지 않는다
  - 감독자도 마무리하지 못하면 기록은 그대로 남는다. 읽는 쪽이 `\n`으로 끝나지 않는 끝 줄을 버리고, `run.end`가 없는 실행 전체를 "중단"으로 표시한다 (읽기는 파일을 고치지 않는다)
- 중첩 트리(서브그래프를 펼쳐 보기)는 뷰어가 `parent`로 만든다

---

## 6. 재시도, 디버거 재개, 화면 속 비밀값

### 재시도

- **관측 재시도**: 캡처·매칭·OCR만 다시 한다. 외부에 영향이 없다
- **액션 재시도**: 클릭·키·실행처럼 게임에 영향을 준다. **MVP에서는 하지 않는다**. 클릭과 관측이 섞인 `core.image.click`도 액션으로 본다
- 노드 타입 스키마가 `retry.mode`를 선언한다: `observation` / `never`. 생략하면 `never`
- 그래프의 노드는 `config.retry`로 **허용된 범위 안에서만** 켠다 (어느 출구에서, 몇 번)
- `max_attempts`는 첫 실행을 포함한다. 기본 1 (재시도 없음). 대기 노드가 타임아웃 안에서 폴링하는 것은 재시도가 아니다
- 재시도는 새 관측으로 시작하고 노드 타임아웃을 다시 주지만, 테스트 전체 기한은 늘리지 않는다
- 재시도는 **출구가 확정되기 전**에만 한다. 중간 실패는 `attempt.end` 이벤트로 남고, 판정에는 마지막 `step.end`만 들어간다. 이미 확정된 fail은 지워지지 않는다. error·취소는 바로 전파한다
- 재시도 끝에 성공한 스텝은 기록에 따로 표시한다 (불안정한 테스트 찾기)
  - 재시도해도 스텝은 하나다(`step.start` 하나). 중간 시도마다 `attempt.end`(`attempt`·`exit`·`status: "fail"`·`outputs`·`message`·`duration_ms`)를 남기고, `step.end`의 `attempt`는 마지막 시도 번호다. 재시도 끝에 성공하면 `step.end`에 `retried: true`
  - `config.retry.on`을 생략하면 노드 스키마의 `retry.on` 전부를 재시도한다
  - 시도마다 스텝 시작 때 계산한 입력의 독립된 복사본을 준다 (앞 시도가 고친 값이 다음 시도로 새지 않는다). 다음 시도를 부르기 전에 취소·기한을 확인하고, `retried: true`는 마지막 확인까지 통과해 성공이 확정된 스텝에만 붙는다

예: `n_wait_lobby`가 20초 안에 로비를 못 찾으면, 아래 설정으로 **대기만** 한 번 더 한다. `n_click_login`을 다시 누르지는 않는다.

```json
{
  "config": {
    "exits": ["error", "lobby"],
    "retry": {
      "max_attempts": 2,
      "on": ["timeout"]
    }
  }
}
```

노드 타입 스키마 쪽 선언 (SDK가 만든다):

```json
{
  "retry": {
    "mode": "observation",
    "on": ["timeout"]
  },
  "type": "core.image.wait_any"
}
```

이후 버전: 구간 재시도(Retry Scope). 서브그래프 하나를 단위로, 재시도할 공개 fail 출구·횟수·상태 복구 절차를 필수로 둔다. 매 시도는 새 호출 프레임이다.

### 디버거로 멈췄다 재개

- 멈춤은 노드 경계나 대기 폴링 사이에서만 확정한다. 진행 중인 클릭이나 워커 호출을 중간에 얼리지 않는다
- **확인 지점 둘** (M3): runner가 멈출지를 정하는 곳은 두 군데다
  1. **스텝 경계**: 스텝을 시작하기 직전(`step.start` 전). 일시정지 요청(그리고 브레이크포인트·Step 목표)을 본다. `debug.pause`의 `step`은 다음에 시작할 스텝, `where: boundary`
  2. **폴링 확인 지점**: 코어 노드의 **멈출 수 있는 기다림**(`ctx.sleep` — 대기 노드의 폴링 사이, `screen.wait_stable`, `flow.delay`) 안. **일시정지 요청만** 본다. 긴 대기·delay 중에도 일시정지가 바로 먹는다. `debug.pause`의 `step`은 기다리던 스텝, `where: poll`이고, 재개하면 남은 활성 시간만큼 마저 기다린다
  - **누르고 있기는 멈추지 않는다**: 입력 서비스의 누르고 있기·드래그 지속 시간은 취소로만 깨는 다른 기다림이다. 그 사이 온 일시정지는 키를 뗀 뒤 다음 확인 지점(그 노드가 폴링하면 다음 폴링, 아니면 다음 경계)에서 확정된다 — 키를 누른 채 멈추지 않는다
  - **워커 노드는 경계에서만** 멈춘다. 워커의 `ctx.sleep`은 워커 프로세스 안 기다림이라 확인 지점이 아니다. 관측 호출(캡처·찾기·OCR) 하나 안에서도 멈추지 않는다
- **시계**: 노드 타임아웃과 테스트 전체 기한 **둘 다** 멈춘 시간을 뺀다 (러너가 멈춤을 확정한 때부터 재개까지). 전체 기한은 무한 루프 방지용이지 게임 시간을 재는 것이 아니다. 브레이크포인트에서 오래 봐도 실행이 죽지 않는다
  - runner는 **활성 시계**(단조 시간 − 멈춘 시간, 멈춘 동안 머묾) 하나로 노드 기한(`ctx.deadline`)·전체 기한·기다림을 잰다. 노드가 만든 기한도 같은 시계라 멈춘 만큼 저절로 늘어난다. 러너의 전체 기한 감시도 같은 시계다
  - **경과는 실제 시간**: `duration_ms`(스텝·시도 `attempt.end`·`run.end`)는 멈춘 시간을 포함한 실제 경과다. 멈춤이 있었던 구간은 `active_duration_ms`(멈춘 시간 제외)를 더 남긴다 — 스텝은 그 스텝 구간에 멈춤이 있었을 때만(경계 멈춤은 그 경계를 감싼 호출 스텝 구간에 든다), `run.end`는 늘
  - 취소 뒤의 마무리 유예·관측 호출의 설정 기한(`run.capture_timeout_ms`)은 실제 시간이다. 멈춘 동안 입력 임대권은 그대로 쥔다
  - M0b의 멈춤(다음 스텝 경계에서만 멈추는 최소 멈춤)은 멈춘 시간을 기한에서 빼지 않았다(멈춘 채 기한이 지나면 `deadline_exceeded`). M3부터 위처럼 뺀다. 멈춘 동안 취소는 바로 먹히고, 취소와 재개가 겹치면 취소가 이긴다(취소되면 `debug.resume`을 쓰지 않는다)
- **브레이크포인트** (M3): 열쇠는 `{graph: 워크스페이스 기준 그래프 경로, node: 노드 ID}`다. 노드 ID는 바뀌지 않으므로(1장) 편집해도 유지된다. exec 노드에만 건다(순수 노드는 스텝이 없다). 러너는 스텝 경계에서만 본다(폴링 확인 지점에서는 보지 않는다). 스냅샷 경로(`snapshot/<경로>`)는 접두를 떼어 비교한다
  - 서브그래프 파일에 건 것은 그 서브그래프가 어느 테스트·어느 호출 노드에서 불리든 적중한다. 반복 본문 노드에 건 것은 회차마다 적중한다(조건·적중 횟수는 이후)
  - 목록은 워크스페이스의 개인 파일 `.kookabug/breakpoints.json`(`breakpoints.schema.json`)이고 daemon이 들고 있다. 실행을 시작할 때 그 순간의 목록을 실행 사양에 넣고, 실행 중 바뀌면 러너에 목록 전체를 밀어 넣는다(다음 경계부터)
- **Step** (M3): 재개 방식(`debug.resume.mode`)이 다음에 멈출 경계를 정한다. 기준은 멈춘 자리의 호출 깊이 `d`(그 스텝 `path` 길이, 폴링에서 멈췄으면 기다리던 스텝의 깊이)다. 반복은 깊이를 더하지 않는다
  - `continue`: 다음 브레이크포인트·일시정지 요청까지
  - `step_over`(다음 노드): 깊이 ≤ `d`인 다음 경계. 호출 노드에서 누르면 서브그래프 안은 지나간다. 반복 노드에서 누르면 본문 첫 노드(같은 깊이)에서 멈춘다
  - `step_into`(들어가기): 다음 경계(깊이 무관). 호출 노드에서 누르면 서브그래프의 첫 스텝(`core.graph.entry`)에서 멈추고, 호출 노드가 아니면 `step_over`와 같은 자리다
  - `step_out`(나오기): 깊이 < `d`인 다음 경계. 맨 바깥에서는 `continue`와 같다
  - 목표 경계에 닿기 전에 브레이크포인트를 만나면 거기서 멈추고(`reason: breakpoint`), 어떤 이유로든 멈추면 목표는 사라진다. 실행이 끝나면 목표도 끝이다. 한 경계에서 여러 이유가 겹치면 `breakpoint` > `step` > `request` 하나만 남긴다
  - 멈추지 않은 실행에 Step을 보내면 아무것도 바꾸지 않고 거절한다(daemon `not_paused`). `continue`는 M0b처럼 멈추지 않았어도 받는다(대기 중인 일시정지 요청을 거둔다)
- **사람이 시작한 실행만** (M3): 브레이크포인트와 디버그 조작(일시정지·재개·Step·다시 시작)은 사람이 앱(UI 연결)에서 시작한 실행에만 적용한다. 에이전트 연결·CLI `kookabug run`·`KOOKABUG_AGENT` 실행은 브레이크포인트 파일이 있어도 멈추지 않는다 — 사람 없는 실행이 멈추면 아무도 재개하지 않은 채 입력 임대권을 쥔다. 디버그 메서드는 에이전트 연결에 거부된다. 멈춘 실행에 UI 연결이 하나도 없는 상태가 10분 이어지면 daemon이 취소한다(실제 시간, 이유 `cancelled`)
- **관측값 무효화**: 재개할 때마다(Step 포함) 실행의 `observation_epoch`를 올린다(0부터, `debug.resume.epoch`). 이전 세대의 화면 관측값(`match`, OCR 결과 등)은 증거로 남지만, 입력이나 분기의 근거로는 쓰지 않는다. 설정값·비밀 입력처럼 화면에서 온 게 아닌 값은 그대로 쓴다. 멈추지 않은 실행은 세대가 0에서 바뀌지 않아 M1과 같다
  - **값의 출처** (M3): 실행기가 값 옆에 "기댄 가장 오래된 관측의 세대"를 붙여 옮긴다. 값 자체는 바꾸지 않는다(노드·워커 계약 그대로). 캡처할 때 그 캡처 번호의 세대를 러너 표에 적는다(워커는 이 표를 보지 못한다)
  - **스텝 관측 바닥**: 스텝마다 "이 스텝이 기댄 가장 오래된 세대"를 둔다. 시작 값은 입력 중 가장 오래된 세대이고, 그 스텝이 캡처할 때마다, 변수에서 읽을 때마다 합친다. **출력 세대 = 그 스텝의 바닥**이다 — 끝난 시각의 세대로 덮어쓰지 않는다(옛 관측에서 나온 값이 새 값으로 세탁되지 않게). 순수 노드 결과·`var.set`으로 넣은 변수·`graph.exit` → 호출 노드 출력도 같은 규칙이다(`graph.entry`·`graph.call`·`graph.exit`은 핀별로 옮긴다). 설정·비밀값·상수·반복 회차(`index`)는 세대가 없다. 재시도의 새 시도는 바닥을 입력에서 다시 잰다
  - **변수**: 변수는 값과 세대를 같이 저장한다. `ctx.vars.get`(코어 노드든 워커 RPC든)이 지금 세대보다 오래된 관측값을 돌려주게 되면, 아래 예외 목록 노드가 아닌 한 돌려주지 않고 처리되지 않은 fail(`stale_observation`)이다. 순수 노드 `var.get`은 돌려주고 세대만 붙인다(그 값을 받는 스텝의 입력 검사가 정한다). 읽은 세대는 그 스텝 바닥에 합치고, `ctx.vars.set`은 그 값에 **지금 스텝 바닥**을 붙인다 — 변수에서 읽은 관측을 가공해 다시 써도 옛 값으로 남는다
  - **스텝 입력 검사**: 스텝 입력을 계산한 직후 노드를 부르기 전에, 지금 세대보다 오래된 관측에서 온 입력이 있으면 그 스텝은 노드를 부르지 않고 처리되지 않은 fail(`stale_observation`, `exit: null`, 메시지에 어느 핀이 어느 노드 관측에서 왔는지)이다. 분기(`flow.branch`·`while`·`repeat`), 검증(`assert.*`), 관측 노드의 영역 입력, 플러그인 노드 모두 여기에 든다 — "오래된 OCR로 분기하지 않음". 예외 둘: ① 오래된 값을 그대로 옮기거나 기록만 하는 코어 노드 `core.log.message`·`core.var.set`·`core.graph.call`·`core.graph.exit`·`core.test.pass/skip/fail`(코어 상수 목록. 플러그인 선언은 이후), ② `input` 효과 노드가 받은 `Match` 값(노드를 부르고 입력 서비스가 다시 찾는다 — 아래). `Match`가 아닌 오래된 값(OCR 글자를 `type_text`에 넣는 등)은 ①이 아니면 fail이다
  - **폴링 재개**: 폴링 확인 지점에서 멈췄다 재개하면 그 스텝이 시작 때 검사해 통과한 입력도 이제 오래된 값일 수 있다(예: OCR 글자를 `ocr.wait_text.contains`에 연결). 그래서 재개 직후, 다음 관측·입력·출구 선택 전에 그 스텝 입력을 위 규칙으로 다시 보고, 오래됐으면 `stale_observation`이다(노드가 삼켜도). 그리고 노드 안 관측(직전 프레임·안정 시작 시각·후보)을 무효로 표시한다. 코어 폴링 노드(대기·찾기 공용 폴링, `screen.wait_stable`, `image.wait_any`)는 그것을 버리고 재개 뒤 프레임으로 처음부터 다시 재며(`wait_stable`의 안정 시간도, `assert.text`가 쥔 마지막 읽은 글자도 — 재개 뒤 못 읽고 끝나면 fail 출구 `text`는 빈 글자), 버렸다고 알리면 바닥이 입력 출처로 돌아간다. 알리지 않는 노드는 바닥이 옛 세대로 남아 출력이 오래된 값이 된다(안전한 쪽)
  - **한계**: 워커가 자기 파이썬 상태에 따로 보관한 값은 추적하지 못한다. 워커 노드는 경계에서만 멈추므로 한 스텝 안에서는 세대가 바뀌지 않고, 스텝을 넘어 몰래 보관하는 것은 노드 계약 위반이다. 워커가 보낸 값의 세대 주장은 믿지 않는다(출력 세대는 러너가 아는 입력·변수 읽기·캡처로 정한다). 예외 ②로 재개 전 `match`를 받은 입력 노드가 그 `match`로 노드 안에서 판단해 좌표 없는 입력(`key`·`type_text`)을 내는 것은 막지 않는다 — 좌표는 위 규칙으로 막지만 판단은 노드 계약이다(받은 `match`는 입력 위치로만 쓴다)
- **재검증**: 입력 노드는 입력 직전에 받은 관측값의 세대를 확인한다. 오래됐으면 스냅샷의 같은 target으로 다시 매칭해서 현재 좌표를 쓴다. 원래 결과는 덮어쓰지 않는다. `$link`가 만든 노드를 다시 실행하지 않는다
  - (M3) 입력 서비스는 `match.frame_info.capture_id`의 세대를 러너 표에서 찾는다. 지금 세대보다 오래됐거나, 세대가 0보다 큰 실행에서 표에 없는 번호(출처 없음)거나, 요청한 스텝이 오래된 관측을 입력으로 받았으면(예외 ②) **크기·DPI가 같아도** 다시 찾는다(그 target의 검색 범위·임계값). 그래서 워커가 옛 `match`의 캡처 번호를 새 것으로 바꿔 보내도 세탁되지 않는다. 그런 스텝(예외 ②)의 `point`·`rect` 입력은 `match`에서 뽑은 좌표일 수 있고 다시 찾을 출처가 없으므로 거절한다(`stale_observation`, 입력 없음 — `match`를 그대로 넘기면 다시 찾는다). 다만 그 스텝의 **출처 없는 입력 핀 값(상수·설정) 그대로인 좌표**는 관측과 무관하므로 받는다 — 예: `input.drag`의 시작점은 재개 전 `match`(다시 찾음), 끝점은 상수 `point`(그대로). 출처 없는 값만 받은 스텝은 거절 자체가 없다. 다시 찾기도 관측 호출이라 기한 규칙을 따른다. 창 바인딩 비교(아래 ①)를 먼저 한다
- 다시 매칭이 안 되거나 출처가 없는 좌표면 처리되지 않은 fail(`stale_observation`)이다 — **입력은 나가지 않는다**. OCR 줄 `match`처럼 `target`이 없는 관측도 재개 뒤에는 그렇다(OCR 글자로 다시 찾기는 이후). 출구를 따로 만들지 않는다 (2장 예외). 이 규칙은 디버거 전용이 아니라 일반 실행에도 적용한다
- **어디서 하나** (M1): runner의 **공용 입력 서비스** 한 곳이다. 코어 입력 노드의 `ctx.input.*`, 워커 플러그인 노드가 SDK로 직접 부른 `ctx.input.*`(RPC), `image.click`·`ocr.click_text` 안의 입력이 모두 이 서비스를 지나고, 입력 액터는 점(클라이언트 물리 픽셀)만 받는다. 그래서 워커 노드도 재검증을 건너뛰지 못한다
- **요청의 창**: 입력 요청은 그 스텝의 대상 창(공통 입력 `in.window`, 없으면 그 스텝 시작 때 호출 프레임의 현재 창)을 만들 때 실어 바뀌지 않는다. 같은 노드가 뒤에 `set_window`를 불러도 이미 그 스텝의 요청은 원래 창으로 간다
- **M1 규칙** (디버거 세대 `observation_epoch`는 위 M3 규칙이 ①과 ② 사이에 든다): `match`를 점으로 줄이기 전에 ① `match.window`와 요청 창을 둘 다 그 실행의 창 바인딩으로 확정해 비교한다(참조가 바인딩 없는 부분 참조여도 빈 칸을 아무 값으로 보지 않는다. 같은 살아 있는 창은 참조 표현이 달라도 바인딩 하나). 관측한 창이 닫혔으면 `window_gone`, 다른 창(같은 HWND에 새로 뜬 창 포함)이면 `window_mismatch`(`error` — 다른 창의 관측 좌표로 입력하지 않는다. `in.window`나 `set_current`로 맞춘다), ② `match.frame_info`의 클라이언트 크기·DPI·캡처 방식이 지금 창과 다르면 `match.target`으로 새 캡처에서 한 번 다시 찾아 그 클릭 지점으로 입력한다(원래 출력은 그대로, 그 스텝 `log`에 남김), ③ 다시 찾지 못했거나 `target`이 없으면 `stale_observation`. 창이 움직이기만 한 것(클라이언트 크기·DPI 같음)은 다시 찾지 않는다 — 좌표가 클라이언트 기준이다. `rect`는 중심, `point`는 그대로(출처가 없어 재검증하지 않는다)
- 노드가 `StaleObservation`을 잡아 삼키고 정상으로 끝내도 그 스텝은 처리되지 않은 fail이다(입력을 하지 않았다). 워커 노드도 같다. `step.end`는 `exit: null`, `message`가 `stale_observation:`으로 시작한다
- 기록: `debug.pause {step, node, graph, path, reason, where}` / `debug.resume {step, mode, epoch, paused_ms}` 이벤트(`paused_ms`는 이번 멈춤), 실행 정보에 개입 여부. `duration_ms`(실제 경과)와 `active_duration_ms`(멈춘 시간 제외)를 나눈다. `run.end`에 `active_duration_ms`·`paused_ms`(멈춘 시간 합)·`debug_intervened`, `run.json`에 그 셋과 `pause_count`. 한 번이라도 멈췄으면 `debug_intervened: true`(브레이크포인트 적중·일시정지 모두)
- 디버거가 개입한 실행은 판정과 별개로 "디버거 개입" 표시를 달고, 성공률·시간 비교에서 기본으로 뺀다

```json
{
  "debug_intervened": true,
  "pause_count": 1,
  "paused_ms": 12000
}
```

### 화면에 찍힌 비밀값

노드별 스크린샷과 기록 뷰어가 이 툴의 핵심이므로 **기록은 기본으로 켠다**. 대신 사용자가 민감한 구간을 지정한다.

| MVP에서 하는 것 | 내용 |
|---|---|
| secret 입력 노드 자동 생략 | `secret` 타입 값을 입력으로 받는 노드는 그 노드의 스크린샷(전·후·실패)을 모두 남기지 않는다. 스텝 시작 때 계산한 입력 값으로 판단한다 (목록·객체 안쪽, `any` 핀으로 온 비밀값 포함). 그 스텝 구간의 영상도 남기지 않는다. 단 서브그래프 호출 노드(`core.graph.call`)의 실패 증거·예외 스크린샷은 호출 노드의 비밀값 입력으로 막지 않는다(구간 끄기·획득 당시 표시는 그대로 본다, 영상 생략도 그대로) — 그 프레임은 안쪽 스텝이 얻은 것이고 비밀값을 직접 받은 안쪽 스텝의 프레임은 획득 당시 표시로 막히므로, 안쪽 스텝 각각이 스스로 남길 수 있는 기록보다 노출이 넓어지지 않는다 |
| 구간 끄기 | 서브그래프·노드에 `record: { "screenshots": "off", "video": "off" }`. 로그인 서브그래프 같은 구간을 통째로 끈다. 호출 노드의 `record`는 그 서브그래프 전체에 간다 |
| 위가 아래를 이긴다 | 워크스페이스 → 테스트 → (호출 노드 → 서브그래프)를 호출 깊이만큼 → 노드 순으로 더한다. 어느 층에서든 끈 것은 하위에서 다시 켤 수 없다. `video`는 `on` < `failed_only` < `off`로 센 쪽이 이긴다 |
| 영상도 같이 | 구간을 끄면 연속 영상과 썸네일도 그 구간을 남기지 않는다. 영상이 켜져 있으면 스크린샷 생략이 의미가 없기 때문 |
| 민감 대상 | target 파일에 `"sensitive": true`면 그 대상으로 읽은 OCR 결과와 그 파생값이 모두 `secret`이 된다 |
| 워크스페이스 정책 | `kookabug.json`의 `record`. 전체 끄기 가능 |
| 예외 스크린샷 | 노드가 `error`로 끝나면 **그 스텝 안에서 얻은 마지막 캡처**를 `steps/<스텝>_error`로 남긴다. 그 스텝에서 캡처하지 않았으면 남기지 않는다 (앞 노드의 캡처를 쓰지 않는다). 서브그래프 안에서 난 오류는 안쪽 스텝이 한 번만 남긴다 |
| 실패 증거 | **fail 출구로 나간 스텝**(연결했든 안 했든 — 서브그래프 호출이면 그 호출 스텝)과 재검증 실패(`stale_observation`) 스텝은 **그 스텝 아래(자기와 안쪽 스텝)에서 얻은 마지막 캡처**를 `steps/<스텝>_fail.png`로 한 번 남긴다. 처리되지 않은 fail의 원인 스텝(실패 위치, `run.end`의 실패 스텝)은 늘 이 스텝들 중 하나라서, 연결 안 된 출구로 바로 확정되든 연결된 fail 분기(로그 노드 등)가 경로 끝에 닿아 확정되든 실패 위치에 증거가 있다. 연결된 분기가 뒤에서 처리돼도(종료 노드·공개 exit) 그 스텝의 증거는 남는다 — fail 출구로 나간 사실의 증거다. 그 아래에서 캡처가 없었으면 남기지 않는다(앞·뒤 노드의 캡처를 쓰지 않는다). 안쪽에서 확정돼 올라오는 fail은 지나가는 호출 스텝이 다시 남기지 않는다. 정책은 예외 스크린샷과 같다 |
| OCR 글자 | 스텝 안에서 마지막으로 읽은 OCR 글자를 `steps/<스텝>_ocr.txt`로 남긴다. 화면에서 읽은 글자도 화면이므로 스크린샷과 같은 정책(구간 끄기·비밀값 입력·획득 당시 표시)을 따르고, 막히면 `omitted`의 `kind: "text"` |
| 민감 대상의 OCR | `sensitive: true` target 영역에서 읽은 글자는 `secret`(숫자는 `null`)이고, 그 스텝의 OCR 글자 기록은 남기지 않는다(`omitted.reason = "sensitive_target"`) |
| 획득 당시 표시 | 러너는 캡처할 때마다 이미지에 실행 안 번호(`capture_id`)를 붙이고 "얻은 스텝에서 스크린샷이 허용됐는가"를 그 번호로 기억한다. 번호는 이미지의 프레임 번호·파일 유무와 상관없이 캡처마다 하나이고, 복사·출력·워커 경계를 넘어도 이미지에 남는다. 저장은 **얻을 때 허용**과 **저장하는 스텝의 허용**을 둘 다 통과해야 한다. 꺼 둔 구간·비밀값 스텝에서 얻은 프레임은 출력으로 나가 켜진 노드가 저장하려 해도 남지 않는다 |
| 생략 이유 기록 | 남기지 않은 증거는 `step.end.omitted`에 `{kind, name, reason, source}`로 적는다. `kind`: `screenshot`·`text`(OCR 글자). `reason`: `secret_input`(비밀값 입력), `policy_off`(구간 끄기), `capture_policy`(얻을 때 막힌 프레임), `sensitive_target`(민감 target 영역의 OCR 글자). `source`: 끈 곳(`kookabug.json#/record`, `<그래프>#/record`, `<그래프>#/nodes/<노드>/record`) 또는 비밀값이 든 입력(`<그래프>#/nodes/<노드>/in/<핀>/…`). 노드의 `ctx.artifacts.save`는 `None`을 받는다. 판정은 바꾸지 않는다 |

```json
{
  "record": {
    "screenshots": "off",
    "video": "off"
  }
}
```

문서로 경고할 것
- secret 입력 노드의 스크린샷을 생략해도, 입력한 값은 **다음 노드 화면**에 남을 수 있다. 로그인 구간은 구간 끄기를 쓴다
- 비밀번호 칸 밖의 계정명·채팅·토큰도 화면에 찍힐 수 있다
- 다른 target으로 같은 영역을 읽으면 `sensitive`가 적용되지 않는다
- 기존 target 이미지와 실행 스냅샷은 자동으로 정리되지 않는다
- 사용자 권한으로 실행되는 플러그인이 직접 파일을 저장하거나 밖으로 보내는 것은 코어 기록 정책으로 막을 수 없다

이후 버전: 영역 가리기(blackout), 화면 속 비밀값 자동 탐지, 움직이는 영역의 영상 마스킹.

---

## 7. 실행 의미

M0a에서 구현하기 전에 확정한 규칙이다. [[구현 계획 v0]] 검토에서 Codex가 짚은 충돌(`$link`는 실행하지 않는다 ↔ 순수 노드는 즉시 계산)을 여기서 정리한다.

### 노드 종류

- **exec 노드**: exec 핀이 있고, exec 흐름이 도착할 때마다 한 번 실행된다
- **순수 노드**(`core.var.get`, `core.logic.compare`, `core.text.format` 등): exec 핀이 없다. **부작용이 없어야 한다**. SDK는 순수 노드의 `ctx`에서 캡처·입력·기록을 막는다

### `$link` 평가

| 연결된 출력 | 규칙 |
|---|---|
| exec 노드의 출력 | 그 노드가 **이미 실행해서 만든 출력**을 읽는다. 노드를 실행시키지 않는다. 출력은 만들어진 호출 프레임과, 그 노드가 속한 반복 범위의 회차에 묶인다 (아래 "반복 범위") |
| 순수 노드의 출력 | 소비하는 노드가 실행될 때 **그 자리에서 계산**한다. 한 번의 소비 안에서는 같은 순수 노드를 한 번만 계산한다(같은 값). 다음 소비 때는 다시 계산한다 |

- 노드의 입력은 스텝이 시작될 때 한 번 계산하고, 재시도 시도 동안 바뀌지 않는다. 예외: `while`의 `condition`은 조건을 검사할 때마다 새로 계산하고, 그때 순수 노드 계산 결과도 새로 시작한다
- `core.var.get`은 계산하는 순간의 변수 값을 준다. 그래서 `while`의 조건은 반복마다 새 값이 된다. 변수가 없으면 `in.default`를 주는데, `default` 키가 없을 때만 `error`다 (`"default": null`은 `null`을 준다)

**실행 전 검증 (정적 규칙)**
- exec 노드의 출력을 읽으려면, 그 생산 노드가 entry에서 소비 노드까지 가는 **모든 exec 경로 위에** 있어야 한다(지배 규칙). 아니면 검증 오류
  - 허용: `wait_any` → 분기 → 합류한 노드가 `wait_any.match`를 읽음 (모든 경로가 `wait_any`를 지남)
  - 거부: 합류한 노드가 한쪽 분기에서만 실행되는 노드의 출력을 읽음
- 순수 노드를 거쳐 읽어도 같다. 순수 노드가 읽는 exec 출력은 **그 순수 노드를 소비하는 exec 노드** 기준으로 검사한다 (전이적)
- 생산 노드가 지배하더라도, 소비 노드로 오는 경로에서 생산 노드가 나간 **출구가 그 출력을 주는지**도 검사한다. 예: `wait`의 `timeout` 출구 뒤에서는 `match`를 읽을 수 없다
- 순수 노드끼리 `$link`로 순환하면(자기 자신을 읽는 것 포함) 검증 오류다. exec 노드의 출력은 이미 만든 값을 읽으므로 순환 판단에 넣지 않는다. 순수 노드가 exec 노드의 출력을 읽고 그 exec 노드가 다시 그 순수 노드를 읽으면 exec 노드가 자기 출력을 읽는 것이라 지배 규칙에서 막힌다
- 실행 중에 그래도 값이 없으면(예상 못 한 경로) `error`
- 실행 중에 순수 노드를 계산하다가 같은 순수 노드로 다시 들어오면(검증을 건너뛴 순환) 무한히 계산하지 않고 `error`다

### 반복

`core.flow.repeat`, `core.flow.while`:

- `body` 출구로 나간 경로가 **끝나면**(연결 안 된 `ok` 출구) 반복 노드로 돌아온다(암묵적 귀환). 본문 끝의 연결 안 된 `ok` 출구는 실행 전 검증 경고 대상이 아니다
- **명시적 exec 순환은 검증 오류**다. 본문 끝을 반복 노드에 직접 연결하거나 일반 노드끼리 순환시킬 수 없다. 반복은 암묵적 귀환으로만 한다 (관측 재시도는 `config.retry`라 exec 이동이 없어 충돌하지 않음)
- `while`의 판단 순서: 조건이 거짓 → `done` / 조건이 참인데 이미 `max_iterations`번 실행함 → `limit` / 아니면 본문 실행. 그래서 마지막 허용 회차에서 조건을 만족시키면 `limit`이 아니라 `done`이다
- 본문에서 처리되지 않은 `fail`이나 `error`가 나면 반복을 멈추고 위로 전파한다
- 본문의 연결된 fail 분기가 처리(예: 로그)를 한 뒤 본문 끝에 닿으면, 그 처리는 실행되지만 **암묵적 귀환은 복구로 인정하지 않는다**. 본문이 끝날 때 처리되지 않은 fail이 남아 있으면 다음 회차로 가지 않고 반복을 멈추고 전파한다
- 이 fail은 어디서 생겼든 같다. 반복 **밖**에서 연결된 fail 출구로 나와 반복으로 들어온 경우도, 종료 노드에 닿지 않은 채 첫 본문 끝에 닿으면 반복을 멈추고 전파한다. 대기 중인 fail은 스텝·재시도 시도·반복 진입·회차 시작 때 지우지 않는다 (종료 노드·공개 exit에 닿아야 처리된다)
- `repeat`의 `times`와 `while`의 `max_iterations`는 반복에 들어갈 때 한 번 정한다. 본문 끝에서 돌아올 때는 한도 입력을 다시 계산하거나 검사하지 않고, `while`의 `condition`만 새로 계산한다 (본문이 한도의 원본 변수를 바꿔도 이 반복에는 영향이 없다)
- 본문에서 `core.test.*` 종료 노드에 도달하면 테스트가 끝나고, 서브그래프의 `core.graph.exit`에 도달하면 서브그래프가 끝난다 (반복도 같이 끝남)
- `limit` 출구는 `fail`이다. 반복에도 테스트 전체 기한이 적용된다

**반복 범위**
- `body` 출구에서 도달할 수 있는 노드들이 그 반복의 **범위**다. 정적으로 계산한다
- 범위끼리는 **완전히 포함되거나 서로 분리**되어야 한다. 부분적으로 겹치면 검증 오류다 (범위를 넘는 합류 금지). 정상적인 중첩 반복은 안쪽 범위가 바깥 범위에 완전히 포함된 경우다
  - 검사는 **단일 진입** 규칙 하나로 한다: 범위 안 노드(종료 노드 제외)로 들어오는 exec 연결은 범위 안 노드나 그 반복 노드의 `body` 출구에서만 와야 한다. 부분 겹침은 어딘가에서 범위 밖 → 안 연결을 만든다
- 본문이 끝나면 **가장 안쪽** 반복 노드로 돌아간다
- **종료 노드는 범위 계산의 경계**다. `core.test.*`와 `core.graph.exit`는 범위 안팎에서 같이 써도 된다 (예: 반복 안의 fail 분기와 밖의 fail 분기가 같은 `core.test.fail`로 감). 그 입력의 지배 검사는 그대로 한다. 본문 안에서만 도달하는 종료 노드는 그 회차의 본문 출력·`index`를 읽을 수 있고(예: 확인 실패 값을 사유에 넣기), 범위 밖에서도 도달하는 종료 노드가 범위 안 출력을 읽으면 오류다. 종료 노드가 아닌 공통 구간(예: 공통 로깅 후 계속 진행)은 범위를 넘어 공유할 수 없다
- 출력 무효화: 안쪽 반복이 다음 회차로 넘어가면 **안쪽 범위의 출력만** 무효가 된다. 바깥 반복이 다음 회차로 넘어가면 바깥 범위 안의 모든 출력(안쪽 범위 포함)이 무효가 된다. 그래서 바깥 본문에서 만든 관측값은 안쪽 반복에서 계속 읽을 수 있다. 무효가 된 출력을 읽으려 하면 오류다
- 범위 밖(`done` 이후 포함)에서 범위 안 노드의 출력을 읽으면 검증 오류다. 값을 밖으로 꺼내려면 `core.var.set`을 쓴다
- 반복 노드의 `index` 출력은 범위 안에서만 읽을 수 있다
- 기록: 반복마다 스텝 ID가 새로 생기고, 이벤트에 `iteration`(0부터)이 붙는다
  - `iteration`은 그 스텝을 감싼 가장 안쪽 반복의 회차다. 반복 노드 자신은 도착할 때마다(처음, 본문 끝에서 돌아올 때) 스텝 하나이고, 나간 출구(`body`·`done`·`limit`)와 `body`면 `index`를 남긴다. 반복 노드 스텝의 `iteration`은 그 바깥 반복의 회차다

### 서브그래프 호출

- 호출마다 새 호출 프레임이다. 안쪽 노드의 출력은 밖에서 직접 읽을 수 없고, `interface.outputs`로만 나온다
- 반복 안에서 같은 서브그래프를 부르면 반복마다 새 프레임이다
- 서브그래프 호출이 순환하면(자기 자신 포함) 실행 전 검증 오류다. 호출 깊이는 테스트에서부터 16단계까지다

---

## 결정 요약

| # | 항목 | 결정 |
|---|---|---|
| 1 | 연결 저장 | exec는 출력 쪽 `next`, data는 입력 쪽 `$link`. `edges` 배열 없음. `$link`는 이번 경로에서 만들어진 값만 읽는다 |
| 2 | 핀과 설정 | 연결할 수 있는 값은 `in`, 연결할 수 없고 노드 모양을 바꾸는 값은 `config`. `wait_any`는 출구 선언·우선순위를 `config.exits` 배열로, 대상 값은 `in.targets`로 |
| 3 | 출구·판정 | 출구마다 `ok` / `fail`. 연결된 fail = 분기이지 복구가 아님. 판정 순서표를 따른다. error·취소는 출구 없이 전파 |
| 4 | 그래프 경계 | `core.graph.entry` / `core.graph.exit` **노드**. 종료 노드(pass/skip/fail)는 테스트 전용 |
| 5 | 현재 대상 창 | 호출 프레임 단위로 이어받는다. 노드의 `window` 입력은 그 노드만. 바꾸려면 명시적 노드 |
| 6 | 특수 값 | `$link`, `$target`, `$setting`, `$secret`, `$literal`. 닫힌 목록 |
| 7 | 찾기 대상 | `*.target.json` 파일로 분리. 이미지는 target 파일 기준 상대 경로 |
| 8 | 서브그래프 참조 | 워크스페이스 기준 경로. 툴 안에서 옮기면 참조를 일괄 수정한다. 툴 밖(Git·탐색기)에서 옮겨 끊어진 참조는 실행 전 검증에서 막는다 |
| 9 | ensure | **넣지 않는다**. 출구별 `screen`은 화면 지도용 정보 |
| 10 | 실행 기록 | 실행 폴더 + 시작 때 스냅샷 + `events.jsonl`. `run`·`step`·`parent`·`attempt`·`exit`·`path`·`graph` 추가 |
| 11 | 노드 ID | 만들 때 정하고 바꾸지 않는다. 이름은 `title`로 |
| 12 | 재시도 | MVP는 관측 재시도만. 노드 타입이 `retry.mode`를 선언하고 그래프는 `config.retry`로 그 안에서 켠다. 기본은 재시도 없음 |
| 13 | 디버거 재개 | 멈춘 시간은 노드·전체 기한에서 뺀다. 재개하면 관측값 세대를 올리고, 입력 노드가 입력 직전에 다시 매칭한다. 실패하면 `stale_observation` |
| 14 | 화면 속 비밀값 | 기록은 기본 켬. secret 입력 노드 자동 생략, 구간 끄기(상위 우선), `sensitive` target, 워크스페이스 전체 끄기 |
| 15 | 실행 의미 | exec 노드 출력은 이미 만든 값만 읽고, 순수 노드는 소비할 때 계산. 지배 규칙(전이적, 출구별 출력 확인). 반복은 암묵적 귀환만(명시적 순환 금지), 범위는 포함 또는 분리, 종료 노드는 공유 가능, 귀환은 복구가 아님 (7장, Codex 검토 반영) |

---

## 리뷰 반영 (2026-10-29, Codex GPT-6-Astra high)

### 1차 (v0.1 → v0.2)

v0.1에서 바뀐 것과 이유.

| 바뀐 것 | 이유 |
|---|---|
| ensure 제거 | 화면만 보고 건너뛰면 다른 계정·서버로 접속한 상태에서도 `success`가 된다. 서브그래프의 입력 계약(`account`, `server`)을 어긴다 |
| 화면 선언을 출구별 `screen`으로 | `start` / `end` 하나로는 `maintenance`, `login_failed`처럼 다른 화면에 남는 출구를 표현할 수 없다 |
| 판정 순서표, "분기 ≠ 복구" | v0.1은 연결 유무가 판정을 정해서, 연결을 지우거나 fail 분기에 로그만 달면 검증 없이 통과할 수 있었다 |
| 검증 없는 테스트는 fail | `시작 → 클릭 → 끝`이 조용히 pass 되는 것을 막는다 |
| 실행 시작 때 스냅샷 | 해시만 남기면 재구성이 안 되고, 실행 도중 편집이 한 실행 안에 섞인다 |
| 노드 ID 불변 | 바꾸면 과거 실행 기록·브레이크포인트·외부 참조가 깨진다 |
| `$literal`, 닫힌 목록 | `$` 키를 가진 일반 JSON 값과 충돌한다 |
| `wait_any` 우선순위를 배열로 | 객체 키 순서는 키 정렬 때문에 의미를 가질 수 없다. 두 대상이 동시에 보이는 경우를 정해야 한다 |
| `$link`는 이번 경로의 값만 | 건너뛴 분기나 지난 반복의 값을 읽으면 조용히 틀린다 |
| `window` 입력은 노드 로컬 | 서브그래프가 창을 바꾸고 돌아왔을 때 다음 노드의 대상이 구현마다 달라진다 |
| `type_text`에 `clear` | 재시도할 때 기존 값에 덧붙여 입력하는 것을 막는다 |
| `run`·`step`·`parent`·`attempt` | `path`만으로는 반복·재호출을 구별할 수 없다 |
| JSONL 이벤트 | 러너가 죽어도 어디까지 실행됐는지 남는다 |

### 2차 (재시도·디버거·비밀값, 6장)

Codex 제안을 기본으로 하고, 세 군데는 Claude가 다르게 정했다 (Codex 동의).

| 항목 | Codex 제안 | 결정 | 이유 |
|---|---|---|---|
| 재검증 실패 | 입력 노드마다 `stale_observation` fail 출구 추가 | 출구 없이 처리되지 않은 fail | 모든 클릭 노드에 출구가 늘어나면 그래프가 지저분해진다 |
| 테스트 전체 기한 | 멈춘 동안에도 흐름 | 멈춘 시간 제외 | 전체 기한은 무한 루프 방지용이다. 브레이크포인트에서 오래 보면 실행이 죽어 디버깅을 못 한다 |
| 기록 기본값 | 스크린샷·영상 기본 끄기, OCR 전체를 비밀로 | 기본 켬 + 민감 구간 지정 | 노드별 스크린샷과 기록 뷰어가 이 툴의 핵심 가치다 |

### M0a 구현 반영

메타스키마(`packages/schema/*.schema.json`)를 만들며 정한 것.

| 바뀐 것 | 이유 |
|---|---|
| 저장 형식(원칙): 키 정렬·2칸 들여쓰기·객체는 항상 펼침·스칼라 배열만 100자 안이면 한 줄·숫자는 JS 표기. 예시 JSON을 이 형식으로 맞춤 | 손으로 맞춘 줄바꿈은 같은 값이 사람마다 다른 바이트가 된다. 너비에 따라 객체를 접으면 값 하나를 고쳐도 형제 필드 줄이 전부 바뀌어 diff가 커진다 |
| 원문 보존(원칙): 값이 그대로면 원문 바이트 유지, 비canonical 파일은 처음 편집해 저장할 때 전체 정규화 | canonical로 다시 쓰는 것만으로는 다른 도구가 만든 파일(4칸 들여쓰기, CRLF, `1.0` 등)의 "열고 그대로 저장하면 바이트가 같음"을 지킬 수 없다 |
| 정수는 ±(2^53-1) 안 (원칙, `number_out_of_range`) | JavaScript 숫자는 그 밖의 정수를 정확히 담지 못해, 에디터에서 열고 저장하면 값이 바뀐다(`2^53+1` → `2^53`) |
| 특수 값은 핀 값 안쪽 어디에나, `$` 키가 섞인 객체는 오류 (1장 "특수 값") | `in.targets.error` 같은 예시가 이미 안쪽에 쓴다. 섞인 객체를 일반 객체로 보면 오타(`$lnik`)가 조용히 상수가 된다 |
| `secret`은 `secret`을 포함한 핀에만, 비밀에서 만든 순수 노드 출력도 비밀 (1장 "비밀값") | 비밀값이 평문 핀으로 흘러 기록에 남는 경로를 연결 검사에서 막는다 |
| 검증 노드 = 노드 스키마의 `assertion` 표시 (2장 판정 5행·실행 전 검증) | `core.assert.*` 이름으로 정하면 플러그인 검증 노드가 판정에 들어가지 못한다 |
| 노드 스키마 입력 핀 `optional: true`(default 없이 생략 가능, default와 같이 쓰지 않음). `var.get`은 `default` 키가 없을 때만 오류, `null`은 값 (7장) | 핀 기본값 `null`로는 "생략"과 "`null`을 줌"을 구분할 수 없다 |
| 테스트의 `core.graph.exit`는 오류, 서브그래프의 연결 안 된 `ok` 출구는 오류(반복 본문 끝 제외) (2장 실행 전 검증) | 테스트와 서브그래프의 끝을 섞으면 판정(테스트)과 반환(서브그래프)이 구분되지 않는다. 서브그래프 경로가 열려 있으면 호출한 쪽이 어느 출구로 나왔는지 알 수 없다 |
| 모든 exit 노드가 nullable 아닌 출력을 줘야 하고 출구별 생략은 없음, nullable은 `null` 채움 (3장 해설) | 출구별 출력을 서브그래프 interface로 선언하는 방법이 없다. 이렇게 하면 호출 노드 출력이 모든 출구에서 주어진다고 볼 수 있어 지배 검사가 단순해진다 |
| `any` 핀은 비밀값도 받는다 (1장 "비밀값"), 호출 순환 금지·깊이 16 (7장 "서브그래프 호출") | `var.set`·`text.format`이 비밀값을 담아야 비밀 전파(G9)가 된다. 순환 호출은 끝나지 않는다 |
| 예시 `n_read_error`의 입력을 `target` → `region`으로 (1장) | `core.ocr.read`의 입력은 `region`이다 ([[MVP 노드 목록]] 5장). 예시를 실행 전 검증에 넣으며 발견 |
| 순수 노드끼리 data 순환 금지(exec 출력 제외), 반복 범위는 단일 진입 규칙으로 검사 (7장 "실행 전 검증"·"반복 범위") | 순수 노드는 소비할 때 계산하므로 서로를 읽으면 끝나지 않는다. "포함 또는 분리"를 연결 하나하나의 규칙으로 바꿔야 어느 연결이 문제인지 가리킬 수 있다 |
| 테스트 전체 기한 초과는 `error`(`deadline_exceeded`) (2장 "출구 종류"), 실행 중 순수 노드 재진입은 `error` (7장 "`$link` 평가"), 비밀값이 `any`를 거쳐 `string` 핀에 닿으면 실행 때 `error` (1장 "비밀값") | 기한은 실행을 끊는 장치라 fail(테스트 결과)로 보면 원인이 가려진다. 검증을 건너뛴 순환·`any`를 거친 값은 정적 검사가 못 막으므로 실행기가 마지막으로 막는다 |
| 반복 밖에서 생긴 대기 중인 fail도 첫 본문 끝에서 반복을 멈추고 전파, 스텝·시도·회차 시작 때 지우지 않음. `times`·`max_iterations`는 반복에 들어갈 때 정함. 반복 노드 스텝과 `iteration` 규칙 (7장 "반복") | 반복이 대기 중인 fail을 지우면 반복 앞의 실패가 반복 뒤의 성공에 덮인다. 본문이 한도 입력을 바꿔 반복이 끝나지 않는 경우를 막는다 |
| 재시도는 스텝 하나, 중간 시도는 `attempt.end`, 재시도 끝 성공은 `retried: true`, `on` 생략은 노드 스키마의 `retry.on` (6장 "재시도") | 이벤트 이름·필드가 정해져야 M0b가 같은 dict를 `events.jsonl`로 쓰고 뷰어가 불안정한 스텝을 찾는다 |

### M0b 구현 반영

| 바뀐 것 | 이유 |
|---|---|
| 실행 폴더에 `logs/`·`input-recovery.json`, 폴더 이름 규칙(UTC 시각·그래프 줄기·`run_id` 8자) (5장 "실행 폴더") | 러너·워커 출력을 파이프 대신 파일로 받아야 감독자가 안 읽어도 막히지 않는다. 눌린 키를 누가 뗐는지 남겨야 두 번 떼지 않는다. 이름만으로 실행을 시간순으로 찾는다 |
| 모든 이벤트에 `seq`·`t`, 이벤트 종류 표, `events`·`run` 메타스키마 (5장 `events.jsonl`) | 잘린 줄·빠진 줄을 `seq`로 알아본다. 형식이 메타스키마로 고정돼야 뷰어·에디터가 같은 필드를 읽는다 |
| 러너가 죽은 실행은 감독자가 마무리(잘린 줄 자르기 → 키 떼기 → 없을 때만 `run.end` → `run.json`), 아무도 마무리하지 못하면 읽기가 "중단" (5장) | 마무리를 두 번 해도 같은 결과여야 감독자가 같은 실행을 다시 열어도 안전하다. 이미 쓴 결과를 덮으면 러너가 확정한 판정이 사라진다 |
| 스냅샷은 스냅샷에서 다시 읽으며 참조를 따라가 파일마다 한 번 복사(고정점), 복사 도중 원본이 바뀌면 처음부터, 원본에도 없는 참조는 검증 오류, 설정은 복사한 `kookabug.json` 기준, 경로가 `.kookabug/` 안을 가리키면(심볼릭 링크·정션 해석, 하드 링크는 제외) 복사하지 않고 `snapshot_private_file` (5장 "실행 시작 때 고정") | 한 번 읽은 참조 목록만 복사하면 서브그래프가 새로 부르는 파일을 놓친다. 원본 기준으로 복사한 것과 실행이 읽는 것이 어긋나지 않게 스냅샷에서 읽는다(설정도 같다). 사라진 파일을 스냅샷 오류로 보면 사용자가 원인(어느 노드의 어느 경로)을 찾기 어렵다. target 이미지 경로에 `../.kookabug/local.json`을 쓰면 개인 설정 원문이 실행 기록에 남는다 |
| 기록 정책: 층 순서(호출 노드 포함)·`video` 강약, 비밀값 입력은 계산한 값으로 판단, 예외 스크린샷은 같은 스텝의 마지막 캡처만, 획득 당시 표시와 저장 스텝을 둘 다 확인, `step.end.omitted`의 이유·위치 (6장 "화면에 찍힌 비밀값") | "실행의 마지막 캡처"를 예외 스크린샷으로 쓰면 꺼 둔 구간·비밀값 스텝의 화면이 뒤 노드의 오류로 다시 기록된다. 프레임은 출력으로 구간 밖에 나갈 수 있어 저장하는 스텝만 보면 막지 못한다. 어느 층이 껐는지 남겨야 사용자가 빠진 스크린샷의 이유를 찾는다 |

### M1 구현 반영

| 바뀐 것 | 이유 |
|---|---|
| target 매칭 규칙: 배율 순서·기대 배율(녹화 높이 → DPI), 첫 성공에서 끝, 색 확인 `match.color_tolerance`(기본 40), 알파 0 마스크, 클릭 지점 = `anchor` + `offset × 배율` (4장) | 같은 target이 DPI·창 크기가 다른 PC에서도 맞아야 한다. 모양 점수만 보면 회색 비활성 버튼을 활성 버튼으로 찾는다. 배경이 바뀌는 버튼은 투명 부분을 빼야 맞는다 |
| 화면 판정 파일 `*.screen.json`(`detect.all`·`none`, 값은 `$target`), 화면 ID = 파일 줄기, `_explored/` 제외, `screen_unknown`(경고)·`screen_ambiguous`(오류, 출구가 가리킨 ID만)·`screen_invalid`(경고) (4장 "화면 판정 파일") | 출구의 `screen`이 가리키는 대상의 형식이 없었다. 화면 지도 전이라 실행을 막지 않되, 가리킨 ID가 두 개면 어느 화면인지 정할 수 없어 오류다 |
| 스냅샷이 출구가 가리킨 화면 파일과 그 target·이미지까지 복사 (5장 "실행 시작 때 고정") | 실행 기록만으로 그때의 화면 정의를 다시 볼 수 있어야 한다. 화면 파일은 ID로 찾으므로 원본 `screens/`에서 찾는다 |
| 입력 직전 재검증을 runner의 공용 입력 서비스 한 곳에서 (코어·워커·`image.click` 입력 모두), 요청 창은 만들 때 고정, M1 규칙 `window_mismatch` → 크기·DPI·캡처 방식이 바뀌었으면 target으로 한 번 다시 찾기 → 못 찾으면 `stale_observation`, 노드가 삼켜도 처리되지 않은 fail (6장 "재검증") | 재검증이 코어 입력 노드에만 있으면 SDK로 직접 클릭하는 워커 노드가 건너뛴다. 다른 창의 관측 좌표로 입력하면 엉뚱한 창을 누른다. 디버거 세대(`observation_epoch`)는 M3라 M1은 창 조건 변화만 본다 |
| 점·사각형 상수 `[x, y]`·`[x, y, w, h]`(클라이언트 픽셀), 검증기가 모양을 보고 실행기가 핀 타입대로 `Point`·`Rect`로 바꿈, `match` 상수 금지 (1장 "상수") | 상수 모양이 없으면 노드마다 따로 해석해 노드끼리 어긋난다. 실행 전 검증이 틀린 모양을 잡아야 실행 중 `error`로 늦게 알지 않는다. `match|point` 핀에 틀린 점이 `match` 항으로 통과하면 검사가 빠진다 |
| 실패 증거 `_fail`(fail 출구로 나간 스텝·재검증 실패 스텝, 그 아래의 마지막 캡처, 한 번), OCR 글자 기록 `_ocr.txt`와 그 생략(`kind: "text"`), 생략 이유 `sensitive_target` (6장 "화면에 찍힌 비밀값") | "실패 위치·스크린샷"의 스크린샷을 남길 곳이 없었다 — 정상적인 fail 출구는 노드가 증거를 남기지 않는다. 처리되지 않은 fail은 경로 끝에서 확정될 수도 있어(fail 출구에 로그 노드만 이음) 그때는 원인 스텝이 이미 닫혀 있다. fail 출구로 나갈 때 그 스텝 자신의 프레임으로 남기면 다른 스텝의 프레임을 쓰지 않고도 실패 위치에 늘 증거가 있다. 화면에서 읽은 글자는 화면과 같은 정책이어야 하고, 민감 target의 글자는 남기지 않는다 |
| 좌표 배열 원소의 `$link`(정적 검사는 개수·연결 타입, 값은 실행 때), 유니온은 실제로 맞는 항으로 변환, 픽셀 상수는 해상도에 따라 바뀌지 않음과 대응 방법, 화면 밖 영역은 `error` (1장 "상수") | 특수 값은 배열 원소에도 온다. 첫 항이 변환을 가로채면 맞는 항의 변환이 빠진다. 큰 해상도에서 적은 영역을 작은 창에서 쓰면 비교할 픽셀이 없는데 "안 변함"으로 판정됐다 |
| 예시 `enter_world`의 출력 `message` 타입 `string` → `string|secret` (1장) | `core.ocr.read`의 `text`는 민감 target이면 비밀값이라 출력 타입이 `string|secret`이다. 실제 노드로 예시를 검증하며 발견 |
| 서브그래프 호출 스텝의 실패 증거·예외 스크린샷은 호출 노드의 비밀값 입력으로 막지 않는다 (6장 "secret 입력 노드 자동 생략") | 로그인 서브그래프에 비밀번호를 넘기는 1·3장 모양이면 로그인 실패 위치(호출 스텝)의 실패 스크린샷이 늘 생략됐다. 그 프레임은 안쪽 스텝 것이고 비밀값을 받은 안쪽 스텝의 프레임은 획득 당시 표시로 막히므로 안쪽 스텝 기록보다 노출이 넓어지지 않는다. 예제 워크스페이스(M1 T12)를 돌리며 발견 |
| 예시 `enter_world`의 fail 출구 화면 `login` → `login_error`, `title` → `maintenance` (1장) | 출구의 `screen`은 그 출구로 나갔을 때 도착하는 화면이다. 로그인 실패·점검 출구로 나가는 순간 화면에는 오류·점검 팝업이 떠 있어, 팝업이 없어야 맞는 `login`·`title` 화면 판정과 어긋났다. 예제 워크스페이스(M1 T12)에서 실패 증거 PNG로 화면 판정을 돌려 발견 |

### M2 구현 반영

| 바뀐 것 | 이유 |
|---|---|
| 원문 보존(원칙): 바이트로 읽기, 무쓰기는 지금 디스크 바이트와 비교, BOM 파일은 읽기 오류 | 로더처럼 텍스트로 읽으면 줄바꿈이 바뀌어(CRLF → LF) 원문을 돌려줄 수 없다. 열 때의 원문과 비교하면 밖에서 바뀐 파일을 내 버전으로 덮어쓰는 저장(값이 원문과 같은 경우)이 아무것도 쓰지 않는다 |
| target 편집기 저장(4장 "편집기 저장"): 합친 revision, `recorded`는 정지 화면에서, 정규화 검색 범위의 픽셀 왕복, 새 PNG는 배타적 생성(같은 바이트면 재사용), JSON 한 번 쓰기가 커밋, 충돌이면 이 저장이 만든 PNG만 되돌림, 에디터 소유 기록에 있는 이미지만 정리, 영역 없이 저장하면 이미지·`recorded` 그대로 JSON만 | PNG를 먼저 덮어쓰고 JSON을 나중에 보면 실패한 저장이 기존 target을 망가뜨린다. "존재 확인 → 덮어쓰기"는 동시 저장에서 성공한 target의 이미지를 바꾸거나 지운다. 어떤 target도 가리키지 않는다는 이유만으로 지우면 사용자가 넣은 원본 PNG가 사라진다. 반올림한 정규화 범위가 원래 픽셀과 달라지면 저장한 범위가 편집기에서 고른 것과 다르다. 사양만 고칠 때 이미지를 다시 자르면 `recorded`가 그 이미지 크기로 바뀌어 기대 배율이 틀어지고 같은 그림의 PNG가 하나 더 생긴다 |

### M3 구현 반영

| 바뀐 것 | 이유 |
|---|---|
| 기록 형식 계약(5장): 실행 폴더 `thumbs/`·`video/`(조각·`segments.jsonl`·`frames.jsonl`·`index.json`, `video-index` 메타스키마), `debug.pause`의 `node`·`graph`·`path`·`reason`·`where`, `debug.resume`의 `mode`·`epoch`·`paused_ms`, `step.end`의 `active_duration_ms`·`evidence`(첫·중간·마지막 캡처와 실제 시각, 중간이 없으면 `null`과 이유, 매칭 후보), `run.end`의 `active_duration_ms`·`paused_ms`·`debug_intervened`·`omitted`(영상 포기), `run.json`의 `active_duration_ms`·`retried_steps`·`observed`·`video`, `Omitted.kind`를 `screenshot`·`text`·`thumbnail`로 고정. 새 필드는 모두 선택이라 M0b~M2 실행 기록이 그대로 읽힌다 | 디버거·영상·기록 뷰어(M3)가 쓸 자리가 스키마에 없었다(`paused_ms`·`active_duration_ms`는 설명만 있고 아무도 쓰지 않았다). 시안의 "실행 전 · 대기 · 시간 초과" 스크린샷과 매칭 후보 점수를 남길 곳이 없었다. 중간 캡처는 끝 시각을 모르는 폴링에서 정확히 고를 수 없어 실제 시각과 편차를 남기고 없을 수도 있게 했다. 영상 조각은 고정 fps라 칸 격자(`t0`·`frame_ms`)가 있어야 재생 위치와 실행 시각을 잇는다 |
| 디버거 멈춤(6장 "디버거로 멈췄다 재개"): 확인 지점 둘(스텝 경계·코어 노드의 멈출 수 있는 기다림 — 일시정지 요청만), 누르고 있기·워커 노드·관측 호출 안에서는 멈추지 않음, 활성 시계 하나로 노드 기한·전체 기한에서 멈춘 시간을 뺌, `duration_ms`는 실제 경과·`active_duration_ms`는 멈춘 시간 제외, `run.end`·`run.json` 멈춤 기록. M0b "멈춘 시간을 빼지 않는다"를 뒤집음 | 대기 노드가 30초를 기다리는 동안에도 일시정지가 바로 먹어야 하고, 같은 기다림을 키 누르고 있기도 쓰면 키를 누른 채 멈춘다(그래서 두 기다림을 나눴다). 브레이크포인트에서 오래 보면 실행이 기한에 죽어 디버깅할 수 없다. 기한 시계로 경과까지 재면 실제 걸린 시간을 잃는다 |
| 브레이크포인트·Step·적용 범위(6장 "디버거로 멈췄다 재개"): 열쇠 = 워크스페이스 기준 그래프 경로 + 노드 ID(서브그래프는 어느 호출에서든, 반복은 회차마다), 경계에서만 봄, Step은 멈춘 자리의 호출 깊이 기준(반복은 깊이를 더하지 않음, 브레이크포인트 > Step > 요청), 멈추지 않은 실행의 Step은 거절, 사람이 UI에서 시작한 실행만(에이전트·CLI 무시, 디버그 메서드는 에이전트 거부), UI 없이 10분 멈추면 취소 | 브레이크포인트를 무엇으로 가리키는지, Step Over·Into의 경계가 없었다(노드 ID 불변이 열쇠다). 사람 없는 실행이 브레이크포인트에서 멈추면 아무도 재개하지 않은 채 입력 임대권을 쥐고, 멈춘 시간을 기한에서 빼므로 기한도 그것을 끝내지 않는다 |
| 관측 세대(6장 "관측값 무효화"·"재검증"): 값 옆 출처(세대) 전파, 스텝 관측 바닥 = 출력 세대, 스텝 입력 검사와 예외 목록(옮기기·기록 코어 노드, `input` 노드의 `Match`), 폴링 재개 직후 입력 재검사와 노드 안 관측 버리기, 변수의 세대(코어·워커 `ctx.vars` 읽기 거부·쓰기에 바닥), 오래된·출처 없는 `match`는 크기와 무관하게 다시 찾기, 워커 내부 상태는 추적 못 함 | "이전 세대 관측값을 분기 근거로 쓰지 않는다"의 결과가 없었다. OCR 글자·숫자는 캡처 번호가 없어 세대를 알 수 없으니 실행기가 붙여 옮겨야 한다. 끝난 시각의 세대로 출력을 찍으면 폴링 중 재개한 노드가 옛 관측을 새 값으로 세탁한다. 워커는 `ctx.vars`로 입력 밖 관측을 가져오므로 변수도 세대를 가져야 한다. M1 재검증은 크기·DPI가 같으면 다시 찾지 않아 멈춘 동안 바뀐 화면을 놓친다 |
