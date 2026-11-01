import type { BuildOptions } from "esbuild";

export declare const APP_DIR: string;
export declare function mainOptions(options?: { release?: boolean; outfile?: string }): BuildOptions;
export declare function preloadOptions(options?: { outfile?: string }): BuildOptions;
