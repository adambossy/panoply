export class FileUploader {
  private listeners: Map<string, Set<Function>> = new Map();

  constructor(
    private input: HTMLInputElement,
    private label: HTMLElement
  ) {
    this.setupListeners();
  }

  private setupListeners(): void {
    this.input.addEventListener('change', async (e) => {
      const file = (e.target as HTMLInputElement).files?.[0];
      if (!file) return;

      this.label.textContent = file.name;
      const content = await file.text();
      this.emit('fileLoaded', content);
    });
  }

  on(event: 'fileLoaded', handler: (content: string) => void): void {
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

