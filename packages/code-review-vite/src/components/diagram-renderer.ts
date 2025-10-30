import mermaid from 'mermaid';
import type { FunctionNode } from '@types';
import { showLoading, showError } from '../utils/dom-helpers';

export class DiagramRenderer {
  private listeners: Map<string, Set<Function>> = new Map();
  private functionNodes: FunctionNode[] = [];
  private initialized = false;

  constructor(private container: HTMLElement) {
    this.initMermaid();
  }

  private initMermaid(): void {
    mermaid.initialize({
      startOnLoad: false,
      theme: 'dark',
      themeVariables: {
        darkMode: true,
        background: '#1e1e1e',
        primaryColor: '#0e639c',
        primaryTextColor: '#d4d4d4',
        primaryBorderColor: '#3e3e42',
        lineColor: '#858585',
        secondaryColor: '#2d2d30',
        tertiaryColor: '#1e1e1e',
      },
    });
    this.initialized = true;
  }

  async render(functions: FunctionNode[], diagramCode: string): Promise<void> {
    if (!this.initialized) {
      this.initMermaid();
    }

    this.functionNodes = functions;
    showLoading(this.container, 'Rendering diagram...');

    try {
      const { svg } = await mermaid.render('diagram', diagramCode);
      this.container.innerHTML = svg;
      this.attachClickHandlers();
    } catch (error) {
      console.error('Error rendering diagram:', error);
      showError(this.container, 'Failed to render diagram');
    }
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

  private attachClickHandlers(): void {
    const nodes = this.container.querySelectorAll('.node');

    nodes.forEach((node, index) => {
      (node as HTMLElement).style.cursor = 'pointer';

      node.addEventListener('click', () => {
        nodes.forEach((n) => n.classList.remove('node-highlight'));
        node.classList.add('node-highlight');

        if (this.functionNodes[index]) {
          this.emit('nodeClick', this.functionNodes[index]);
        }
      });
    });
  }

  destroy(): void {
    this.listeners.clear();
    this.container.innerHTML = '';
  }
}

