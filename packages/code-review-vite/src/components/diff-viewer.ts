import type { DiffFile, FunctionNode } from '@types';
import { escapeHtml } from '../utils/escape-html';
import { showEmptyState } from '../utils/dom-helpers';

export class DiffViewer {
  private listeners: Map<string, Set<Function>> = new Map();

  constructor(private container: HTMLElement) {
    this.setupTextSelectionHandler();
  }

  private setupTextSelectionHandler(): void {
    document.addEventListener('mouseup', () => {
      const selection = window.getSelection();
      const selectedText = selection?.toString().trim();

      if (selectedText) {
        const range = selection?.getRangeAt(0);
        if (range && this.container.contains(range.commonAncestorContainer)) {
          this.emit('textSelect', selectedText);
        }
      }
    });
  }

  showFunction(file: DiffFile, funcNode: FunctionNode): void {
    const html = this.generateFunctionHTML(file, funcNode);
    this.container.innerHTML = html;
  }

  showFile(file: DiffFile): void {
    const html = this.generateFileHTML(file);
    this.container.innerHTML = html;
  }

  clear(): void {
    showEmptyState(this.container, 'Select a node in the diagram to see the relevant diff');
  }

  private generateFunctionHTML(file: DiffFile, funcNode: FunctionNode): string {
    let html = '<div class="diff-file">';
    html += `<div class="diff-file-header">${file.newPath || file.oldPath} :: ${funcNode.name}()</div>`;
    html += '<div class="diff-lines">';

    const targetHunk = funcNode.hunk;
    let oldLine = targetHunk.oldStart;
    let newLine = targetHunk.newStart;

    const funcLineIdx = targetHunk.lines.findIndex((l) => l.content.includes(funcNode.fullLine.trim()));

    const startIdx = Math.max(0, funcLineIdx - 5);
    const endIdx = Math.min(targetHunk.lines.length, funcLineIdx + 30);

    for (let i = 0; i < startIdx; i++) {
      const line = targetHunk.lines[i]!;
      if (line.type === 'deletion' || line.type === 'context') oldLine++;
      if (line.type === 'addition' || line.type === 'context') newLine++;
    }

    for (let i = startIdx; i < endIdx; i++) {
      const line = targetHunk.lines[i]!;
      const lineClass = line.type;
      let lineNum = '';

      if (line.type === 'deletion') {
        lineNum = String(oldLine++);
      } else if (line.type === 'addition') {
        lineNum = String(newLine++);
      } else {
        lineNum = String(newLine++);
        oldLine++;
      }

      const isTargetLine = i === funcLineIdx;
      const style = isTargetLine ? ' style="background: #264f78 !important;"' : '';

      html += `<div class="diff-line ${lineClass}"${style}>`;
      html += `<span class="line-number">${lineNum}</span>`;
      html += `<span class="line-content">${escapeHtml(line.content)}</span>`;
      html += '</div>';
    }

    html += '</div></div>';
    return html;
  }

  private generateFileHTML(file: DiffFile): string {
    let html = '<div class="diff-file">';
    html += `<div class="diff-file-header">${file.newPath || file.oldPath}</div>`;
    html += '<div class="diff-lines">';

    file.hunks.forEach((hunk) => {
      let oldLine = hunk.oldStart;
      let newLine = hunk.newStart;

      hunk.lines.forEach((line) => {
        const lineClass = line.type;
        let lineNum = '';

        if (line.type === 'deletion') {
          lineNum = String(oldLine++);
        } else if (line.type === 'addition') {
          lineNum = String(newLine++);
        } else {
          lineNum = String(newLine++);
          oldLine++;
        }

        html += `<div class="diff-line ${lineClass}">`;
        html += `<span class="line-number">${lineNum}</span>`;
        html += `<span class="line-content">${escapeHtml(line.content)}</span>`;
        html += '</div>';
      });
    });

    html += '</div></div>';
    return html;
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

