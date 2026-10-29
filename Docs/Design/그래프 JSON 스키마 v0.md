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
- **정수 범위**: 그래프·target·워크스페이스 파일의 정수는 ±(2^53-1) 안이어야 한다. 넘으면 형식 검사 오류(`number_out_of_range`). JavaScript(에디터)에서 값이 조용히 바뀌는 것을 막는다. 더 큰 수(ID 등)는 문자열로 쓴다. 유한한 실수는 제한하지 않는다
- **비유한 값**: NaN·Infinity는 JSON 값이 아니다. 파일을 읽을 때 `NaN`·`Infinity` 토큰과 float 범위를 넘는 수(`1e400`)는 읽기 오류다. 프로그램(에디터·에이전트)이 직접 넘긴 값에 NaN·±Infinity가 있으면 형식 검사 오류(`number_not_finite`)이고, 저장(canonical)도 거부한다
- 그래프에 `plugins`(플러그인 버전)와 노드마다 `version`(노드 타입 버전)을 기록한다
- 테스트와 서브그래프는 **같은 형식**이고 `kind`만 다르다

## 예시 파일 구성

```
workspace/
├─ subgraphs/enter_world.graph.json   서브그래프: 게임시작 → 로그인 → 월드 접속
├─ tests/inventory_open.graph.json    테스트: 월드 접속 후 인벤토리 열기 확인
└─ targets/                            찾기 대상 (이미지 + 임계값 + 검색 범위 + 클릭 지점)
   ├─ title/start_button.target.json
   ├─ title/start_button.png
   └─ ...
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
        "screen": "login"
      },
      "maintenance": {
        "kind": "fail",
        "screen": "title"
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
        "type": "string"
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
- 여러 그래프가 같은 대상을 쓰므로 파일로 분리한다 (UiPath Object Repository). 사용처 추적은 target 파일과 PNG까지 포함한다

---

## 5. 실행 기록

### 실행 폴더

```
runs/2026-10-29T15-02-11_inventory_open_r8k2/
├─ run.json        run_id, 대상 테스트, 러너·플러그인·의존성 버전, 게임 빌드, 실행 조건
├─ events.jsonl    시작·종료 이벤트. 실행 중에도 한 줄씩 덧붙인다
├─ snapshot/       실행 시작 때 복사한 그래프·서브그래프·타깃·이미지·화면 정의
└─ steps/          스크린샷 등 artifacts
```

- **실행 시작 때 고정**: 러너는 시작할 때 테스트가 참조하는 모든 파일을 따라가 `snapshot/`에 복사하고, 실행 내내 그 복사본만 읽는다. 실행 중에 서브그래프나 이미지를 고쳐도 이번 실행에는 섞이지 않는다
- 비밀값은 복사하지 않는다. 참조 키(`accounts.qa_tester_01`)만 남긴다
- 당시 실행 정의를 재구성할 수는 있지만, 게임 서버 상태까지 되돌릴 수는 없다. "같은 정의로 다시 실행"과 "같은 결과 재현"은 다르다

### `events.jsonl` (일부)

```jsonl
{"event": "step.start", "node": "n_enter_world", "parent": null, "path": ["n_enter_world"], "run": "r8k2", "step": "s1", "t": "2026-10-29T15:02:12.104Z"}
{"attempt": 1, "event": "step.start", "node": "n_wait_title", "parent": "s1", "path": ["n_enter_world", "n_wait_title"], "run": "r8k2", "step": "s2", "t": "2026-10-29T15:02:13.010Z"}
{"artifacts": ["steps/s2_before.png", "steps/s2_after.png"], "duration_ms": 8120, "event": "step.end", "exit": "found", "outputs": {"match": {"score": 0.93, "window": "w1", "xywh": [812, 701, 296, 88]}}, "run": "r8k2", "status": "success", "step": "s2", "t": "2026-10-29T15:02:21.130Z"}
{"duration_ms": 41230, "event": "step.end", "exit": "success", "graph": "snapshot/subgraphs/enter_world.graph.json", "outputs": {"message": null}, "run": "r8k2", "status": "success", "step": "s1", "t": "2026-10-29T15:02:53.334Z"}
```

- 확정된 노드 결과(`status`, `outputs`, `error`, `artifacts`, `duration_ms`)에 더하는 필드
  - `run`, `step`, `parent`: 실행과 스텝 인스턴스 ID. 같은 노드가 반복·재호출돼도 구별된다
  - `attempt`: 재시도 번호
  - `exit`: 어느 exec 출구로 나갔는지
  - `path`: 호출 경로. 실패 위치를 `월드 접속 > 타이틀 대기`처럼 보여 줄 때 쓴다
  - `graph`: 서브그래프 호출이면 이번 실행에 쓴 스냅샷 파일
- `step.end`가 없는 스텝은 러너가 중간에 죽은 것이다. 뷰어는 "중단"으로 표시한다
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
- **시계**: 노드 타임아웃과 테스트 전체 기한 **둘 다** 멈춘 시간을 뺀다 (러너가 멈춤을 확정한 때부터 재개까지). 전체 기한은 무한 루프 방지용이지 게임 시간을 재는 것이 아니다. 브레이크포인트에서 오래 봐도 실행이 죽지 않는다
- **관측값 무효화**: 재개할 때마다 실행의 `observation_epoch`를 올린다. 이전 세대의 화면 관측값(`match`, OCR 결과 등)은 증거로 남지만, 입력이나 분기의 근거로는 쓰지 않는다. 설정값·비밀 입력처럼 화면에서 온 게 아닌 값은 그대로 쓴다
- **재검증**: 입력 노드는 입력 직전에 받은 관측값의 세대를 확인한다. 오래됐으면 스냅샷의 같은 target으로 다시 매칭해서 현재 좌표를 쓴다. 원래 결과는 덮어쓰지 않는다. `$link`가 만든 노드를 다시 실행하지 않는다
- 다시 매칭이 안 되거나 출처가 없는 좌표면 처리되지 않은 fail(`stale_observation`)이다. 출구를 따로 만들지 않는다 (2장 예외). 이 규칙은 디버거 전용이 아니라 일반 실행에도 적용한다
- 기록: `debug.pause` / `debug.resume` 이벤트, 실행 정보에 개입 여부. `duration_ms`(실제 경과)와 `active_duration_ms`(멈춘 시간 제외)를 나눈다
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
| secret 입력 노드 자동 생략 | `secret` 타입 값을 입력으로 받는 노드는 그 노드의 스크린샷(전·후·실패)을 모두 남기지 않는다 |
| 구간 끄기 | 서브그래프·노드에 `record: { "screenshots": "off", "video": "off" }`. 로그인 서브그래프 같은 구간을 통째로 끈다 |
| 위가 아래를 이긴다 | 상위(워크스페이스 → 테스트 → 서브그래프 → 노드)에서 끈 것은 하위에서 다시 켤 수 없다 |
| 영상도 같이 | 구간을 끄면 연속 영상과 썸네일도 그 구간을 남기지 않는다. 영상이 켜져 있으면 스크린샷 생략이 의미가 없기 때문 |
| 민감 대상 | target 파일에 `"sensitive": true`면 그 대상으로 읽은 OCR 결과와 그 파생값이 모두 `secret`이 된다 |
| 워크스페이스 정책 | 전체 끄기 가능 |
| 생략 이유 기록 | 남기지 않은 증거에는 "정책으로 생략"이라고 적는다. 판정은 바꾸지 않는다 |

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
