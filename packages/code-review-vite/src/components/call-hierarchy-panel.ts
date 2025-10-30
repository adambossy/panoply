import type { CallHierarchy } from '@types';
import { escapeHtml } from '../utils/escape-html';
import { showEmptyState } from '../utils/dom-helpers';

export class CallHierarchyPanel {
  constructor(private container: HTMLElement) {
    this.setupToggleHandlers();
  }

  private setupToggleHandlers(): void {
    this.container.addEventListener('click', (e) => {
      const target = e.target as HTMLElement;
      if (target.classList.contains('hierarchy-section-header')) {
        const sectionId = target.dataset.section;
        if (sectionId) {
          this.toggleSection(sectionId);
        }
      }
    });
  }

  show(hierarchy: CallHierarchy | null): void {
    if (!hierarchy) {
      showEmptyState(this.container, 'No function detected in selection');
      return;
    }

    const html = this.generateHTML(hierarchy);
    this.container.innerHTML = html;
  }

  private generateHTML(h: CallHierarchy): string {
    let html = '<div class="target-symbol">';
    html += `<h3>${escapeHtml(h.targetFunction)}</h3>`;
    html += `<code>${escapeHtml(h.signature)}</code>`;
    html += '</div>';

    html += this.generateSection('incoming', 'Incoming Calls', h.incomingCalls.length);
    html += '<div id="incoming-section" class="call-tree">';

    if (h.incomingCalls.length === 0) {
      html += '<div class="empty-state" style="padding: 1rem;">No incoming calls found</div>';
    } else {
      h.incomingCalls.forEach((call) => {
        html += '<div class="call-site">';
        html += '<div class="call-link">';
        html += `<span class="symbol-name">${escapeHtml(call.file)}</span>`;
        html += `<span class="location">Line ${call.line}</span>`;
        html += `<span class="call-type-badge">${call.type}</span>`;
        html += '</div>';
        html += `<pre class="context-code">${escapeHtml(call.content)}</pre>`;
        html += '</div>';
      });
    }
    html += '</div>';

    html += this.generateSection('outgoing', 'Outgoing Calls', h.outgoingCalls.length);
    html += '<div id="outgoing-section" class="call-tree">';

    if (h.outgoingCalls.length === 0) {
      html += '<div class="empty-state" style="padding: 1rem;">No outgoing calls found</div>';
    } else {
      h.outgoingCalls.forEach((call) => {
        html += '<div class="call-site">';
        html += '<div class="call-link">';
        html += `<span class="symbol-name">${escapeHtml(call.functionName || '')}</span>`;
        html += `<span class="location">${escapeHtml(call.file)}:${call.line}</span>`;
        html += '</div>';
        html += `<pre class="context-code">${escapeHtml(call.content)}</pre>`;
        html += '</div>';
      });
    }
    html += '</div>';

    return html;
  }

  private generateSection(id: string, title: string, count: number): string {
    return `
      <div class="hierarchy-section">
        <button class="hierarchy-section-header" data-section="${id}">
          <span>▼</span> ${title} (${count})
        </button>
      </div>
    `;
  }

  private toggleSection(sectionId: string): void {
    const section = this.container.querySelector(`#${sectionId}-section`) as HTMLElement;
    if (section) {
      section.style.display = section.style.display === 'none' ? 'block' : 'none';
    }
  }

  clear(): void {
    showEmptyState(this.container, 'Select code in the diff to view call hierarchy');
  }

  destroy(): void {
    // Cleanup if needed
  }
}

