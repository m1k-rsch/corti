export declare const name = "corti-memory";
export declare const inject: string[];
export interface Config {
    baseUrl(v: string): string;
    appId(v: string): string;
    projectId(v: string): string;
    userId(v: string): string;
    agentId(v: string): string;
    recallTopK(v: number): number;
    injectTopK(v: number): number;
    startupTopK(v: number): number;
    maxInjectChars(v: number): number;
    autoCapture(v: boolean): boolean;
}
export declare function apply(ctx: any, config: Config): Promise<void>;
