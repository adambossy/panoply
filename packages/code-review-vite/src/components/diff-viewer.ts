import type { DiffFile, FunctionNode } from '@types';

export class DiffViewer {
  private listeners: Map<string, Set<Function>> = new Map();

  constructor(private container: HTMLElement) {
    // Mark fields/methods as used to satisfy noUnusedLocals during scaffolding
    void this.container;
    void this.emit;
  }

  showFunction(file: DiffFile, funcNode: FunctionNode): void {
    // TODO: Implementation in Phase 2
    void file;
    console.log('DiffViewer.showFunction called for', funcNode.name);
  }

  showFile(file: DiffFile): void {
    // TODO: Implementation in Phase 2
    console.log('DiffViewer.showFile called for', file.newPath);
  }

  on(event: 'textSelect', handler: (text: string) => void): void {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, new Set());
    }
    this.listeners.get(event)!.add(handler);
  }

  private emit(event: string, ...args: any[]): void {
    this.listeners.get(event)?.forEach((handler) => handler(...args));
  }

  destroy(): void {
    this.listeners.clear();
  }
}

