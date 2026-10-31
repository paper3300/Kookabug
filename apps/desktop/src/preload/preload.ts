// 샌드박스 preload: contextBridge로 좁은 API만 내놓는다
import { contextBridge, ipcRenderer } from "electron";
import { createBridge } from "./bridge";

contextBridge.exposeInMainWorld("kookabug", createBridge(ipcRenderer));
