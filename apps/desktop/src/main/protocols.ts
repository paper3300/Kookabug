// app:// (렌더러 빌드 폴더)와 kbimg:// (편집기 캐시·워크스페이스 이미지) 서비스 (M2 계획 2.4·2.10).
// 경로 판정은 security.ts에 있고 여기서는 응답만 만든다
import { pathToFileURL } from "node:url";
import { net, protocol } from "electron";
import {
  APP_SCHEME,
  cspHeaderValue,
  fileResponse,
  isAppUrl,
  KBIMG_SCHEME,
  resolveAppFile,
  resolveKbimgPath,
  VIDEO_EXTENSION,
} from "./security";

/** app.whenReady 전에 부른다 */
export function registerSchemes(): void {
  protocol.registerSchemesAsPrivileged([
    { scheme: APP_SCHEME, privileges: { standard: true, secure: true, supportFetchAPI: true } },
    // stream: <video>가 kbimg 영상을 Range로 나눠 읽는다 (M3 2.7)
    { scheme: KBIMG_SCHEME, privileges: { standard: true, secure: true, stream: true } },
  ]);
}

/**
 * @param rendererRoot 렌더러 빌드 폴더
 * @param workspaceRoot 지금 열린 워크스페이스 루트 (없으면 null). kbimg는 요청마다 다시 읽는다
 */
export function handleProtocols(rendererRoot: string, workspaceRoot: () => string | null): void {
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
