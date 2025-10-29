import type { FunctionNode } from '@types';

export class DiagramRenderer {
  private listeners: Map<string, Set<Function>> = new Map();

  constructor(private container: HTMLElement) {
    // Mark fields/methods as used to satisfy noUnusedLocals during scaffolding
    void this.container;
    void this.emit;
  }

  async render(functions: FunctionNode[]): Promise<void> {
    // TODO: Implementation in Phase 2
    console.log('DiagramRenderer.render called with', functions.length, 'functions');
  }

  on(event: 'nodeClick', handler: (funcNode: FunctionNode) => void): void {
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

