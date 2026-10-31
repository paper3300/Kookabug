// 검사용: 그래프 말뭉치(fixtures/graph-corpus/corpus.json) 읽기. 검사 파일만 쓴다
import fs from "node:fs";
import path from "node:path";
import type { GraphValue } from "./model";

export const REPO = path.resolve(import.meta.dirname, "..", "..", "..", "..", "..");
export const CORE_SCHEMA = path.join(REPO, "python", "kookabug_nodes", "src", "kookabug_nodes", "kookabug.schema.json");

export const CORPUS_FILES = (
  JSON.parse(fs.readFileSync(path.join(REPO, "fixtures", "graph-corpus", "corpus.json"), "utf8")) as { files: string[] }
).files;

export function readCorpus(rel: string): GraphValue {
  return JSON.parse(fs.readFileSync(path.join(REPO, rel), "utf8").replace(/^﻿/, "")) as GraphValue;
}

export function readCoreSchema(): unknown {
  return JSON.parse(fs.readFileSync(CORE_SCHEMA, "utf8").replace(/^﻿/, ""));
}

/** 고치려 하면 던지게 얼린다 (명령이 앞 값을 바꾸지 않는지) */
export function deepFreeze<T>(v: T): T {
  if (typeof v === "object" && v !== null) {
    for (const k of Object.keys(v)) deepFreeze((v as Record<string, unknown>)[k]);
    Object.freeze(v);
  }
  return v;
}
