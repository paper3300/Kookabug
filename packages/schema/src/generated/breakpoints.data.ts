/* 생성물 (packages/schema/*.schema.json → scripts/gen.mjs). 직접 고치지 않는다. */

export const breakpointsSchema: unknown = {
  "$defs": {
    "Breakpoint": {
      "additionalProperties": false,
      "description": "브레이크포인트 열쇠: 그래프 파일 + 노드 ID (노드 ID는 바뀌지 않는다). exec 노드에만 건다. 서브그래프 파일에 건 것은 어느 호출에서든, 반복 본문 노드에 건 것은 회차마다 적중한다",
      "properties": {
        "graph": {
          "description": "노드가 든 그래프 파일 (워크스페이스 루트 기준 '/' 구분 경로, 스냅샷 접두 없음)",
          "minLength": 1,
          "pattern": "^[^\\\\]+\\.graph\\.json$",
          "type": "string"
        },
        "node": {
          "description": "노드 ID (graph.schema.json NodeId)",
          "pattern": "^[A-Za-z_][A-Za-z0-9_-]{0,63}$",
          "type": "string"
        }
      },
      "required": [
        "graph",
        "node"
      ],
      "title": "Breakpoint",
      "type": "object"
    },
    "BreakpointList": {
      "description": "브레이크포인트 목록 (순서 무관, 같은 항목은 하나로 본다)",
      "items": {
        "$ref": "#/$defs/Breakpoint"
      },
      "maxItems": 1000,
      "title": "BreakpointList",
      "type": "array"
    }
  },
  "$id": "urn:kookabug:breakpoints:0",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": false,
  "description": "브레이크포인트 파일 (.kookabug/breakpoints.json, 개인 파일). daemon이 원자적 교체로 쓰고, 사람이 UI에서 시작한 실행에만 넣는다",
  "properties": {
    "breakpoints": {
      "$ref": "#/$defs/BreakpointList"
    },
    "format": {
      "const": "kookabug.breakpoints/0"
    }
  },
  "required": [
    "breakpoints",
    "format"
  ],
  "title": "Breakpoints",
  "type": "object"
};
