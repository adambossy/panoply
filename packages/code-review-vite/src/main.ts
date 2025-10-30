import './styles/main.css';

import { DiagramRenderer } from '@components/diagram-renderer';
import { DiffViewer } from '@components/diff-viewer';
import { CallHierarchyPanel } from '@components/call-hierarchy-panel';
import { FileUploader } from '@components/file-uploader';

import { getElement } from './utils/dom-helpers';
import { parseDiff } from '@lib/diff-parser';
import { extractFunctions } from '@lib/function-extractor';
import { generateMermaidDiagram } from '@lib/diagram-generator';
import { extractCallHierarchy } from '@lib/call-hierarchy-analyzer';

/**
 * Code Review Tool - Main Application
 */
class CodeReviewApp {
  private diagram: DiagramRenderer;
  private diffViewer: DiffViewer;
  private hierarchyPanel: CallHierarchyPanel;
  private uploader: FileUploader;

  private parsedDiff: any = null;
  private currentFile: any = null;

  constructor() {
    // Initialize components
    this.diagram = new DiagramRenderer(getElement('#mermaid-diagram'));
    this.diffViewer = new DiffViewer(getElement('#diff-content'));
    this.hierarchyPanel = new CallHierarchyPanel(getElement('#call-hierarchy-content'));

    const fileInput = getElement<HTMLInputElement>('#diff-file');
    const fileName = getElement('#file-name');
    this.uploader = new FileUploader(fileInput, fileName);

    // Mark fields as used during scaffolding
    void this.parsedDiff;
    void this.currentFile;

    this.setupEventHandlers();
    console.log('Code Review Tool initialized');
  }

  private setupEventHandlers(): void {
    // File upload
    this.uploader.on('fileLoaded', (content) => {
      this.handleFileLoad(content);
    });

    // Diagram interactions
    this.diagram.on('nodeClick', (funcNode) => {
      this.handleNodeClick(funcNode);
    });

    // Text selection for call hierarchy
    this.diffViewer.on('textSelect', (text) => {
      this.handleTextSelection(text);
    });
  }

  private async handleFileLoad(content: string): Promise<void> {
    try {
      this.parsedDiff = parseDiff(content);
      console.log('Parsed diff:', this.parsedDiff);
      console.log('Files found:', this.parsedDiff.files.length);

      const functions = extractFunctions(this.parsedDiff);
      console.log('Functions found:', functions.length);
      console.log('Functions:', functions);

      const diagramCode = generateMermaidDiagram(functions, this.parsedDiff);
      console.log('Mermaid diagram:', diagramCode);
      await this.diagram.render(functions, diagramCode);
    } catch (error) {
      console.error('Error parsing diff:', error);
    }
  }

  private handleNodeClick(funcNode: any): void {
    console.log('Node clicked:', funcNode);
    const file = this.parsedDiff?.files.find(
      (f: any) => f.newPath === funcNode.file || f.oldPath === funcNode.file
    );
    if (file) {
      this.currentFile = file;
      this.diffViewer.showFunction(file, funcNode);
    }
  }

  private handleTextSelection(text: string): void {
    if (!this.currentFile || !this.parsedDiff) return;
    const hierarchy = extractCallHierarchy(text, this.currentFile, this.parsedDiff);
    this.hierarchyPanel.show(hierarchy);
  }

  destroy(): void {
    this.diagram.destroy();
    this.diffViewer.destroy();
    this.hierarchyPanel.destroy();
    this.uploader.destroy();
  }
}

// Initialize app when DOM is ready
const app = new CodeReviewApp();

// Make app globally accessible for debugging
(window as any).app = app;
