// app:// (렌더러 빌드 폴더)와 kbimg:// (편집기 캐시·워크스페이스 이미지) 서비스 (M2 계획 2.4·2.10),
// kbplugin:// (플러그인 위젯, M6 계획 3.10). 경로 판정은 security.ts에 있고 여기서는 응답만 만든다
import fs from "node:fs";
import { pathToFileURL } from "node:url";
import { net, protocol } from "electron";
import {
  APP_SCHEME,
  cspHeaderValue,
  fileResponse,
  isAppUrl,
  KBIMG_SCHEME,
  KBPLUGIN_SCHEME,
  pluginHeaders,
  resolveAppFile,
  resolveKbimgPath,
  resolvePluginUrl,
  VIDEO_EXTENSION,
  widgetShell,
} from "./security";
import type { WidgetHosts } from "./widgets";

/** app.whenReady 전에 부른다 */
export function registerSchemes(): void {
  protocol.registerSchemesAsPrivileged([
    { scheme: APP_SCHEME, privileges: { standard: true, secure: true, supportFetchAPI: true } },
    // stream: <video>가 kbimg 영상을 Range로 나눠 읽는다 (M3 2.7)
    { scheme: KBIMG_SCHEME, privileges: { standard: true, secure: true, stream: true } },
    // 위젯: 플러그인마다 다른 호스트(출처). corsEnabled: 불투명 출처 iframe이 ES 모듈을 CORS로 읽는다.
    // bypassCSP·supportFetchAPI 없음 (위젯 CSP가 네트워크를 막는다)
    { scheme: KBPLUGIN_SCHEME, privileges: { standard: true, secure: true, corsEnabled: true } },
  ]);
}

/**
 * kbplugin:// 요청 → 응답. 껍데기는 처리기가 만들고, 자원은 그 플러그인 ui 폴더 파일만. 껍데기·자원 모두 요청마다
 * 그 호스트의 환경이 지금도 잠금에 있고 준비됐는지 daemon에 확인한다 (검증에서 탈락하면 이미 뜬 위젯의 새 요청도 거부)
 */
export async function pluginResponse(request: Request, hosts: WidgetHosts): Promise<Response> {
  const url = request.url;
  const host = /^kbplugin:\/\/([^/?#]+)/i.exec(url)?.[1]?.toLowerCase() ?? "";
  const entry = await hosts.lookup(host);
  const result = resolvePluginUrl(url, (h) => (entry !== null && entry.host === h ? entry : null));
  if (!result.ok) return new Response(result.reason, { status: 404, headers: { "Content-Type": "text/plain" } });
  if (result.kind === "shell") {
    return new Response(widgetShell(), { status: 200, headers: pluginHeaders(result.host, "text/html; charset=utf-8") });
  }
  return new Response(fs.readFileSync(result.file), { status: 200, headers: pluginHeaders(result.host, result.contentType) });
}

/**
 * @param rendererRoot 렌더러 빌드 폴더
 * @param workspaceRoot 지금 열린 워크스페이스 루트 (없으면 null). kbimg는 요청마다 다시 읽는다
 * @param hosts 위젯 호스트 표 (daemon plugins.list)
 */
export function handleProtocols(rendererRoot: string, workspaceRoot: () => string | null, hosts: WidgetHosts): void {
  protocol.handle(KBPLUGIN_SCHEME, (request) => pluginResponse(request, hosts));
  protocol.handle(APP_SCHEME, async (request) => {
    const file = isAppUrl(request.url) ? resolveAppFile(request.url, rendererRoot) : null;
    if (file === null) return new Response("not found", { status: 404 });
    const res = await net.fetch(pathToFileURL(file).toString());
    const headers = new Headers(res.headers);
    headers.set("Content-Security-Policy", cspHeaderValue());
    headers.set("X-Content-Type-Options", "nosniff");
    return new Response(res.body, { status: res.status, headers });
  });
  protocol.handle(KBIMG_SCHEME, async (request) => {
    const result = resolveKbimgPath(request.url, workspaceRoot());
    if (!result.ok) return new Response(result.reason, { status: 404 });
    if (result.file.toLowerCase().endsWith(VIDEO_EXTENSION)) {
      // 영상 탐색: Range 요청은 206 부분 응답 (net.fetch는 file: Range를 넘기지 않는다)
      return fileResponse(result.file, request.headers.get("range"));
    }
    const res = await net.fetch(pathToFileURL(result.file).toString());
    const headers = new Headers(res.headers);
    // 편집기 캐시 PNG는 같은 이름으로 다시 쓰이지 않지만, 워크스페이스 PNG는 바뀔 수 있다
    headers.set("Cache-Control", "no-store");
    headers.set("X-Content-Type-Options", "nosniff");
    return new Response(res.body, { status: res.status, headers });
  });
}
