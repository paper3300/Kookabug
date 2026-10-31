// 창 닫기 확인 (M2 계획 T9 "닫을 때 저장 확인", 검수 1차). 창 X·메뉴 "끝내기"·OS 닫기(Alt+F4·작업 표시줄)는 모두
// BrowserWindow "close" 이벤트로 온다. 렌더러가 확인 경로를 붙였으면 닫기를 한 번 막고 렌더러에 묻는다
// (app.closeRequested). 렌더러가 저장·버림을 고르면 closeAnswer(true)로 다시 닫고, 취소면 그대로 둔다.
// 렌더러가 없거나 죽었으면(붙이지 않음·다시 읽는 중) 막지 않는다. electron을 import하지 않아 vitest로 검사한다

export interface CloseGuardDeps {
  /** 렌더러에 닫기 확인을 부탁한다 */
  ask(): void;
  /** 확인이 끝난 창을 실제로 닫는다 */
  close(): void;
}

export class CloseGuard {
  private armed = false;
  private asking = false;
  private allowed = false;

  constructor(private readonly deps: CloseGuardDeps) {}

  /** 렌더러가 확인 경로를 붙이거나(true) 뗀다(false) */
  arm(on: boolean): void {
    this.armed = on;
    if (!on) this.asking = false;
  }

  /** 렌더러가 사라짐 (죽음·다시 읽기): 막지 않는다 */
  rendererGone(): void {
    this.arm(false);
  }

  /** "close" 이벤트. true를 돌려주면 막는다(event.preventDefault) */
  onClose(): boolean {
    if (this.allowed || !this.armed) return false;
    if (!this.asking) {
      this.asking = true;
      this.deps.ask();
    }
    return true;
  }

  /** 렌더러의 답: true면 닫는다 */
  answer(ok: boolean): void {
    if (!this.asking) return;
    this.asking = false;
    if (!ok) return;
    this.allowed = true;
    this.deps.close();
  }
}
