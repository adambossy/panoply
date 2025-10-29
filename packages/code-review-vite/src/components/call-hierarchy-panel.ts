import type { CallHierarchy } from '@types';

export class CallHierarchyPanel {
  constructor(private container: HTMLElement) {}

  show(hierarchy: CallHierarchy | null): void {
    // TODO: Implementation in Phase 2
    console.log('CallHierarchyPanel.show called with', hierarchy);
  }

  clear(): void {
    this.container.innerHTML = '<div class="empty-state">Select code in the diff to view call hierarchy</div>';
  }

  destroy(): void {
    // Cleanup if needed
  }
}

