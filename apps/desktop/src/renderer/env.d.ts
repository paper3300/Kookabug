/// <reference types="vite/client" />
import type { KookabugBridge } from "../preload/bridge";

declare global {
  interface Window {
    readonly kookabug: KookabugBridge;
  }
}
