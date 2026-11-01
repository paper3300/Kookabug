// 응답이 늦게 오는 요청의 세대 확인 (T9 문서 표·T12 target 표 공용).
// 요청을 보낼 때 문서의 세대 칸(instance·편집 수·다시 열기 요청 번호·프레임 세대 등)을 적어 두고, 응답이 온 순간
// 그 칸이 그대로인지 본다. 요청을 시작할 때만 확인하면 응답을 기다리는 동안 생긴 편집·더 새 요청·닫았다 다시 연
// 문서를 옛 응답이 덮는다 (T9 검수 1차, T12 검수 1차)

/** 요청 시점의 세대 칸 */
export type Stamp<D, K extends keyof D> = Readonly<Pick<D, K>>;

export function stampOf<D, K extends keyof D>(doc: D, keys: readonly K[]): Stamp<D, K> {
  const out = {} as Pick<D, K>;
  for (const k of keys) out[k] = doc[k];
  return out;
}

/** 문서가 아직 있고 적어 둔 세대 칸이 모두 같은가 */
export function sameStamp<D extends object, K extends keyof D>(doc: D | undefined, stamp: Stamp<D, K>): doc is D {
  if (doc === undefined) return false;
  for (const k of Object.keys(stamp) as K[]) if (!Object.is(doc[k], stamp[k])) return false;
  return true;
}
