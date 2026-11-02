/* 생성물 (packages/schema/*.schema.json → scripts/gen.mjs). 직접 고치지 않는다. */

export const runIndexSchema: unknown = {
  "$defs": {
    "CallPath": {
      "description": "호출 경로: 테스트부터의 호출 노드들 + 노드",
      "items": {
        "type": "string"
      },
      "minItems": 1,
      "title": "CallPath",
      "type": "array"
    },
    "CompareEnvDiff": {
      "additionalProperties": false,
      "description": "환경 차이 한 줄 (같은 값은 넣지 않는다). key는 observed.dpi·conditions.profile·conditions.settings.<키>·packages.<이름>·plugins.<ID>·game_build 같은 점 경로. 비밀값 설정은 값 없이 키만",
      "properties": {
        "baseline": {
          "description": "기준 실행의 값 (없으면 null)"
        },
        "key": {
          "minLength": 1,
          "type": "string"
        },
        "run": {
          "description": "이 실행의 값 (없으면 null)"
        }
      },
      "required": [
        "baseline",
        "key",
        "run"
      ],
      "title": "CompareEnvDiff",
      "type": "object"
    },
    "CompareGraph": {
      "additionalProperties": false,
      "description": "스냅샷 비교. 해시 = 스냅샷 폴더 파일마다 sha256을 내고, 상대 경로('/' 구분) 순으로 '경로\\0파일 sha256\\n' 줄을 이어 낸 sha256. 한쪽이라도 스냅샷 폴더가 없으면(예전 실행) CompareResult에 graph가 없다",
      "properties": {
        "baseline_hash": {
          "$ref": "#/$defs/Sha256"
        },
        "changed": {
          "items": {
            "additionalProperties": false,
            "properties": {
              "change": {
                "enum": [
                  "added",
                  "modified",
                  "removed"
                ]
              },
              "path": {
                "description": "스냅샷 안 경로 (워크스페이스 기준)",
                "minLength": 1,
                "type": "string"
              }
            },
            "required": [
              "change",
              "path"
            ],
            "type": "object"
          },
          "type": "array"
        },
        "hash": {
          "$ref": "#/$defs/Sha256"
        },
        "same": {
          "type": "boolean"
        }
      },
      "required": [
        "baseline_hash",
        "changed",
        "hash",
        "same"
      ],
      "title": "CompareGraph",
      "type": "object"
    },
    "CompareResult": {
      "additionalProperties": false,
      "description": "run.compare 결과: 지난 성공(기준 실행)과의 차이. 기준 실행이 없으면 baseline이 null이고 나머지 비교는 없다",
      "properties": {
        "baseline": {
          "anyOf": [
            {
              "$ref": "#/$defs/RunId"
            },
            {
              "type": "null"
            }
          ]
        },
        "baseline_picked": {
          "description": "auto: 같은 테스트·같은 프로필·pass·디버거 개입 아님 중 가장 최근, user: 요청이 고름",
          "enum": [
            "auto",
            "user"
          ]
        },
        "env": {
          "items": {
            "$ref": "#/$defs/CompareEnvDiff"
          },
          "type": "array"
        },
        "graph": {
          "$ref": "#/$defs/CompareGraph"
        },
        "message": {
          "description": "기준 실행이 없을 때의 안내 (예: 비교할 성공 실행 없음)",
          "type": "string"
        },
        "run_id": {
          "$ref": "#/$defs/RunId"
        },
        "screen": {
          "$ref": "#/$defs/CompareScreen"
        },
        "time": {
          "$ref": "#/$defs/CompareTime"
        }
      },
      "required": [
        "baseline",
        "run_id"
      ],
      "title": "CompareResult",
      "type": "object"
    },
    "CompareScreen": {
      "additionalProperties": false,
      "description": "화면 차이: 실패 스텝(또는 고른 스텝)의 증거와 기준 실행의 같은 호출 경로·같은 노드 썸네일(남은 마지막 회차)을 같은 크기 회색조로 줄여 비교. 호출 스텝이면 그 증거를 캡처한 안쪽 스텝의 경로로 찾고(그 스텝에 기준 썸네일이 없으면 다른 노드로 넘어가지 않고 reason), 안쪽 스텝을 모를 때만 기준 실행에서 그 호출 경로 아래의 마지막 썸네일을 쓴다(baseline_step은 실제로 쓴 스텝). 비교하지 못하면 reason. reason도 diff_ratio도 없으면 이 환경에서 화면 차이를 계산할 수 없다(플랫폼 없음)",
      "properties": {
        "baseline_file": {
          "description": "기준 실행 폴더 기준 파일 (thumbs/<스텝>.jpg)",
          "type": [
            "null",
            "string"
          ]
        },
        "baseline_step": {
          "anyOf": [
            {
              "$ref": "#/$defs/StepId"
            },
            {
              "type": "null"
            }
          ]
        },
        "diff_ratio": {
          "description": "달라진 픽셀 비율 (0~1)",
          "maximum": 1,
          "minimum": 0,
          "type": "number"
        },
        "file": {
          "description": "이 실행 폴더 기준 파일 (steps/<스텝>_fail.png 등)",
          "type": [
            "null",
            "string"
          ]
        },
        "reason": {
          "description": "비교하지 못한 이유. policy_omitted: 정책으로 남기지 않음, no_thumbnail: 기준 실행에 썸네일 없음, no_evidence: 이 실행에 증거 없음, no_matching_step: 기준 실행에 같은 노드 스텝 없음, image_unreadable: 두 이미지 중 하나를 읽지 못함(파일이 깨졌거나 사라짐)",
          "enum": [
            "image_unreadable",
            "no_evidence",
            "no_matching_step",
            "no_thumbnail",
            "policy_omitted"
          ]
        },
        "regions": {
          "description": "차이 영역 상자 (이 실행 증거 이미지 좌표)",
          "items": {
            "$ref": "#/$defs/Rect"
          },
          "maxItems": 5,
          "type": "array"
        },
        "step": {
          "$ref": "#/$defs/StepId"
        }
      },
      "required": [
        "baseline_file",
        "baseline_step",
        "file",
        "step"
      ],
      "title": "CompareScreen",
      "type": "object"
    },
    "CompareTime": {
      "additionalProperties": false,
      "description": "시간 비교. 경과는 멈춤을 뺀 값(스텝에 active_duration_ms가 있으면 그것)",
      "properties": {
        "debug_intervened": {
          "description": "이 실행이 디버거로 멈췄던 실행: 회차 경과가 벽시계라 변곡을 내지 않는다(inflections는 빈 목록)",
          "type": "boolean"
        },
        "inflections": {
          "description": "반복 스텝(step, 노드는 반복 노드)의 회차 전체 경과에서 앞 절반 중앙값의 2배를 넘는 경과가 3회차(남은 회차가 적으면 남은 전부, 최소 2) 이어지기 시작한 첫 회차. 회차 4개 이상만, 최대 20개. 앞 1/4쯤 안에서 늦어지기 시작하면 앞 절반 중앙값이 이미 늦은 값이라 잡지 못한다. body_*는 그 반복 본문(회차 바로 아래 스텝)에서 변곡 전·후 평균이 가장 많이 는 노드",
          "items": {
            "additionalProperties": false,
            "properties": {
              "after_ms": {
                "description": "변곡 회차부터의 회차 경과 중앙값",
                "minimum": 0,
                "type": "number"
              },
              "before_ms": {
                "description": "앞 절반 회차 경과 중앙값",
                "minimum": 0,
                "type": "number"
              },
              "body_after_ms": {
                "description": "body_node의 변곡 회차부터 평균 경과",
                "minimum": 0,
                "type": "number"
              },
              "body_before_ms": {
                "description": "body_node의 변곡 전 평균 경과",
                "minimum": 0,
                "type": "number"
              },
              "body_node": {
                "description": "본문에서 가장 많이 늦어진 노드 (반복 노드와 같은 그래프)",
                "type": "string"
              },
              "from_iteration": {
                "minimum": 0,
                "type": "integer"
              },
              "graph": {
                "type": "string"
              },
              "node": {
                "type": "string"
              },
              "step": {
                "$ref": "#/$defs/StepId"
              }
            },
            "required": [
              "after_ms",
              "before_ms",
              "from_iteration",
              "graph",
              "node",
              "step"
            ],
            "type": "object"
          },
          "type": "array"
        },
        "nodes": {
          "description": "노드별 평균 경과 비교 (한쪽에만 있으면 그쪽 값은 null)",
          "items": {
            "additionalProperties": false,
            "properties": {
              "baseline_count": {
                "minimum": 0,
                "type": "integer"
              },
              "baseline_mean_ms": {
                "minimum": 0,
                "type": [
                  "null",
                  "number"
                ]
              },
              "count": {
                "minimum": 0,
                "type": "integer"
              },
              "graph": {
                "type": "string"
              },
              "mean_ms": {
                "minimum": 0,
                "type": [
                  "null",
                  "number"
                ]
              },
              "node": {
                "type": "string"
              }
            },
            "required": [
              "baseline_count",
              "baseline_mean_ms",
              "count",
              "graph",
              "mean_ms",
              "node"
            ],
            "type": "object"
          },
          "type": "array"
        }
      },
      "required": [
        "inflections",
        "nodes"
      ],
      "title": "CompareTime",
      "type": "object"
    },
    "IterationSummary": {
      "additionalProperties": false,
      "description": "반복 스텝의 회차 하나 (회차 안 스텝은 run.children으로 읽는다). status는 회차 안 스텝 중 가장 나쁜 결과 (error > fail > cancelled > aborted > running > success)",
      "properties": {
        "duration_ms": {
          "minimum": 0,
          "type": [
            "integer",
            "null"
          ]
        },
        "iteration": {
          "minimum": 0,
          "type": "integer"
        },
        "status": {
          "$ref": "#/$defs/StepStatus"
        },
        "steps": {
          "description": "회차 안 스텝 수 (안쪽 호출 포함)",
          "minimum": 0,
          "type": "integer"
        },
        "t_start": {
          "$ref": "#/$defs/Timestamp"
        }
      },
      "required": [
        "duration_ms",
        "iteration",
        "status",
        "steps",
        "t_start"
      ],
      "title": "IterationSummary",
      "type": "object"
    },
    "NodeStat": {
      "additionalProperties": false,
      "description": "노드별 통계 (그래프·노드마다, 끝난 스텝만)",
      "properties": {
        "count": {
          "minimum": 0,
          "type": "integer"
        },
        "error": {
          "minimum": 0,
          "type": "integer"
        },
        "fail": {
          "minimum": 0,
          "type": "integer"
        },
        "graph": {
          "type": "string"
        },
        "last_failure_step": {
          "anyOf": [
            {
              "$ref": "#/$defs/StepId"
            },
            {
              "type": "null"
            }
          ]
        },
        "max_ms": {
          "minimum": 0,
          "type": "integer"
        },
        "mean_ms": {
          "minimum": 0,
          "type": "number"
        },
        "node": {
          "type": "string"
        },
        "p95_ms": {
          "minimum": 0,
          "type": "number"
        },
        "success": {
          "minimum": 0,
          "type": "integer"
        }
      },
      "required": [
        "count",
        "error",
        "fail",
        "graph",
        "last_failure_step",
        "max_ms",
        "mean_ms",
        "node",
        "p95_ms",
        "success"
      ],
      "title": "NodeStat",
      "type": "object"
    },
    "PauseSpan": {
      "additionalProperties": false,
      "description": "멈춘 구간 (debug.pause ~ debug.resume, 재개 없이 끝났으면 t_end null)",
      "properties": {
        "mode": {
          "enum": [
            "continue",
            "step_into",
            "step_out",
            "step_over"
          ]
        },
        "reason": {
          "enum": [
            "breakpoint",
            "request",
            "step"
          ]
        },
        "step": {
          "anyOf": [
            {
              "$ref": "#/$defs/StepId"
            },
            {
              "type": "null"
            }
          ]
        },
        "t_end": {
          "anyOf": [
            {
              "$ref": "#/$defs/Timestamp"
            },
            {
              "type": "null"
            }
          ]
        },
        "t_start": {
          "$ref": "#/$defs/Timestamp"
        },
        "where": {
          "enum": [
            "boundary",
            "poll"
          ]
        }
      },
      "required": [
        "step",
        "t_end",
        "t_start"
      ],
      "title": "PauseSpan",
      "type": "object"
    },
    "Rect": {
      "description": "[x, y, w, h] 픽셀",
      "items": {
        "maximum": 9007199254740991,
        "minimum": -9007199254740991,
        "type": "integer"
      },
      "maxItems": 4,
      "minItems": 4,
      "title": "Rect",
      "type": "array"
    },
    "RunId": {
      "description": "실행 ID: 소문자·숫자 8자",
      "pattern": "^[a-z0-9]{8}$",
      "title": "RunId",
      "type": "string"
    },
    "Sha256": {
      "pattern": "^[0-9a-f]{64}$",
      "title": "Sha256",
      "type": "string"
    },
    "StepId": {
      "pattern": "^s[1-9][0-9]*$",
      "title": "StepId",
      "type": "string"
    },
    "StepNode": {
      "additionalProperties": false,
      "description": "색인의 스텝 하나 (events.jsonl의 step.start·attempt.end·step.end를 합친 것). 반복 스텝(iterations가 있음)의 status·exit·t_end·duration_ms·message는 반복 전체다: 반복 노드에 마지막으로 도착한 스텝이 반복을 끝냈으면(done·한도 fail) 그 스텝 것, 본문 실패·중단으로 돌아오지 못했으면 마지막 회차의 가장 나쁜 결과(그 회차가 성공뿐이면 진행 중 실행은 running·t_end null, 끝난 실행은 aborted)와 그 회차 끝 시각, exit null. duration_ms는 첫 도착 시작부터 그 끝까지(벽시계). active_duration_ms는 없다. 노드별 통계(stats)는 도착마다의 실제 스텝 값이다",
      "properties": {
        "active_duration_ms": {
          "description": "멈춘 시간을 뺀 경과 (step.end에 있을 때만)",
          "minimum": 0,
          "type": "integer"
        },
        "artifacts": {
          "description": "실행 폴더 기준 증거 파일 (step.end.artifacts)",
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        "attempt": {
          "minimum": 1,
          "type": "integer"
        },
        "calls": {
          "description": "서브그래프 호출이면 부른 그래프 (워크스페이스 기준)",
          "type": "string"
        },
        "children": {
          "description": "바로 아래 스텝 수 (반복이면 모든 회차 합)",
          "minimum": 0,
          "type": "integer"
        },
        "duration_ms": {
          "minimum": 0,
          "type": [
            "integer",
            "null"
          ]
        },
        "evidence": {
          "description": "step.end.evidence가 있다 (run.step으로 읽는다)",
          "type": "boolean"
        },
        "exit": {
          "type": [
            "null",
            "string"
          ]
        },
        "graph": {
          "description": "노드가 든 그래프 (워크스페이스 기준. 실행 때 쓴 스냅샷은 실행 폴더 snapshot/ 아래 같은 경로)",
          "type": "string"
        },
        "iteration": {
          "description": "parent가 반복 스텝일 때 그 회차 (본문 스텝은 events의 iteration, 되돌아옴은 방금 끝난 회차)",
          "minimum": 0,
          "type": "integer"
        },
        "iterations": {
          "description": "반복 스텝이면 회차별 요약 (회차 순)",
          "items": {
            "$ref": "#/$defs/IterationSummary"
          },
          "type": "array"
        },
        "message": {
          "type": "string"
        },
        "node": {
          "type": "string"
        },
        "omitted": {
          "items": {
            "$ref": "urn:kookabug:events:0#/$defs/Omitted"
          },
          "type": "array"
        },
        "parent": {
          "anyOf": [
            {
              "$ref": "#/$defs/StepId"
            },
            {
              "type": "null"
            }
          ],
          "description": "색인 부모: 호출 스텝, 또는 반복 스텝(반복 노드에 처음 도착한 스텝). 반복은 실행기에서 깊이를 더하지 않아 events의 parent와 다를 수 있다: 본문 스텝과 본문이 끝나 반복 노드로 되돌아온 스텝이 반복 스텝 아래 회차로 묶인다. 최상위는 null"
        },
        "path": {
          "$ref": "#/$defs/CallPath"
        },
        "retried": {
          "description": "재시도 끝에 성공 (step.end.retried)",
          "type": "boolean"
        },
        "status": {
          "$ref": "#/$defs/StepStatus"
        },
        "step": {
          "$ref": "#/$defs/StepId"
        },
        "t_end": {
          "anyOf": [
            {
              "$ref": "#/$defs/Timestamp"
            },
            {
              "type": "null"
            }
          ]
        },
        "t_start": {
          "$ref": "#/$defs/Timestamp"
        },
        "thumbnail": {
          "description": "썸네일 파일이 있다 (thumbs/<스텝>.jpg, 파일 유무가 기준)",
          "type": "boolean"
        }
      },
      "required": [
        "attempt",
        "children",
        "duration_ms",
        "evidence",
        "exit",
        "graph",
        "node",
        "parent",
        "path",
        "status",
        "step",
        "t_end",
        "t_start"
      ],
      "title": "StepNode",
      "type": "object"
    },
    "StepStatus": {
      "description": "step.end의 status, 또는 step.end가 없는 스텝: running(진행 중 실행), aborted(끝난 실행에서 중단)",
      "enum": [
        "aborted",
        "cancelled",
        "error",
        "fail",
        "running",
        "success"
      ],
      "title": "StepStatus",
      "type": "string"
    },
    "Timestamp": {
      "description": "UTC 시각, 밀리초까지 (2026-10-29T06:02:11.104Z)",
      "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3}Z$",
      "title": "Timestamp",
      "type": "string"
    },
    "VideoView": {
      "additionalProperties": false,
      "description": "뷰어가 쓰는 영상 정보: video/index.json이 있으면 그 내용, 없으면 segments.jsonl에서 읽은 조각·빈 구간 (finalized false)",
      "properties": {
        "finalized": {
          "description": "index.json(마무리 결과)에서 읽었다",
          "type": "boolean"
        },
        "gaps": {
          "items": {
            "$ref": "urn:kookabug:video-index:0#/$defs/Gap"
          },
          "type": "array"
        },
        "reason": {
          "$ref": "urn:kookabug:video-index:0#/$defs/VideoReason"
        },
        "segments": {
          "items": {
            "$ref": "urn:kookabug:video-index:0#/$defs/Segment"
          },
          "type": "array"
        },
        "status": {
          "$ref": "urn:kookabug:video-index:0#/$defs/VideoStatus"
        }
      },
      "required": [
        "finalized",
        "gaps",
        "segments",
        "status"
      ],
      "title": "VideoView",
      "type": "object"
    }
  },
  "$id": "urn:kookabug:run-index:0",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": false,
  "description": "실행 색인 (run.index 결과). 코어 record/index.py가 events.jsonl을 한 번 훑어 만든다. 최상위 스텝과 실패 사슬의 스텝만 담고, 그 밖의 스텝은 run.children으로 쪽마다 읽는다",
  "properties": {
    "failure_chain": {
      "description": "루트부터 실패 스텝(run.end.failure_step)까지의 스텝 (실패가 없으면 빈 목록)",
      "items": {
        "$ref": "#/$defs/StepId"
      },
      "type": "array"
    },
    "last_seq": {
      "description": "색인에 넣은 마지막 이벤트 seq (진행 중 실행은 구독 커서와 맞춘다)",
      "minimum": 0,
      "type": "integer"
    },
    "pauses": {
      "items": {
        "$ref": "#/$defs/PauseSpan"
      },
      "type": "array"
    },
    "run": {
      "description": "run.json 내용 그대로 (형식은 run.schema.json, 아직 없으면 null)",
      "type": [
        "null",
        "object"
      ]
    },
    "run_dir": {
      "description": "실행 폴더 (워크스페이스 기준, kbimg://ws/<run_dir>/<파일>로 연다)",
      "type": "string"
    },
    "run_id": {
      "$ref": "#/$defs/RunId"
    },
    "state": {
      "enum": [
        "ended",
        "running"
      ]
    },
    "stats": {
      "items": {
        "$ref": "#/$defs/NodeStat"
      },
      "type": "array"
    },
    "steps": {
      "description": "최상위 스텝과 실패 사슬의 스텝 (step 번호 순)",
      "items": {
        "$ref": "#/$defs/StepNode"
      },
      "type": "array"
    },
    "video": {
      "anyOf": [
        {
          "$ref": "#/$defs/VideoView"
        },
        {
          "type": "null"
        }
      ],
      "description": "video/ 폴더가 없으면 null"
    }
  },
  "required": [
    "failure_chain",
    "last_seq",
    "pauses",
    "run",
    "run_dir",
    "run_id",
    "state",
    "stats",
    "steps",
    "video"
  ],
  "title": "RunIndex",
  "type": "object"
};
