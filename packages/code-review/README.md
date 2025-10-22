# Code Review Tool

A lightweight web-based code review tool built with Astro and Mermaid that visualizes git diffs as interactive dataflow diagrams.

## Features

- **Visual Dataflow Diagram**: Automatically generates Mermaid diagrams from git diffs showing modified files and their relationships
- **Interactive Split Pane UI**: Click on any node in the diagram to see the corresponding diff in the adjacent pane
- **Smart Relationship Detection**: Analyzes imports and dependencies to infer connections between files
- **Syntax-Highlighted Diffs**: Clear visualization of additions, deletions, and context lines
- **Dark Theme**: Easy-on-the-eyes dark mode interface optimized for code review

## Quick Start

### Development

```bash
# From the packages/code-review directory
npm install
npm run dev
```

The app will be available at `http://localhost:4321`

### Production Build

```bash
npm run build
npm run preview
```

## Usage

1. **Generate a Git Diff**
   ```bash
   # From your repository root
   git diff > my-changes.diff

   # Or for a specific commit range
   git diff main..feature-branch > feature.diff
   ```

2. **Load the Diff**
   - Open the Code Review Tool in your browser
   - Click "Load Git Diff" button
   - Select your `.diff` or `.patch` file

3. **Review the Changes**
   - The left pane shows a Mermaid diagram with all modified files
   - Each node displays the filename and change count (±N lines)
   - Arrows indicate detected relationships (imports, dependencies)
   - Click any node to view the full diff in the right pane

## How It Works

### Diff Parsing
The tool parses standard git diff format, extracting:
- File paths (old and new)
- Hunks with line numbers
- Additions, deletions, and context lines
- Change statistics per file

### Dataflow Analysis
The diagram generator:
1. Creates a node for each modified file
2. Analyzes added lines for import statements
3. Infers relationships between files based on imports/requires
4. Generates Mermaid graph syntax with styling

### Interactive Visualization
- Mermaid renders the graph with dark theme
- Click handlers on nodes sync with diff display
- Split-pane layout for simultaneous viewing

## Architecture

```
src/
└── pages/
    └── index.astro          # Main application (single-page)
        ├── HTML/CSS         # Split-pane layout
        └── JavaScript       # Diff parser, Mermaid generator, interactivity
```

### Key Components

**parseDiff(diffText)**
- Parses git diff output into structured format
- Returns: `{ files: [{ oldPath, newPath, hunks, additions, deletions }] }`

**generateMermaidDiagram(diff)**
- Creates Mermaid graph definition from parsed diff
- Infers file relationships from import statements
- Returns: Mermaid syntax string

**renderDiagram(diagramCode)**
- Renders Mermaid diagram using mermaid.js
- Injects SVG into DOM

**setupInteractivity()**
- Attaches click handlers to diagram nodes
- Syncs node selection with diff display

**displayDiff(file)**
- Renders diff with syntax highlighting
- Shows line numbers and change indicators

## Technologies

- **Astro 5**: Static site generator with zero-JS by default
- **Mermaid 11**: Diagram generation and rendering
- **Vanilla JS**: No framework dependencies for runtime
- **CSS Grid/Flexbox**: Responsive split-pane layout

## Limitations

- Client-side only (no server required)
- Relationship detection is heuristic (based on simple pattern matching)
- Works best with diffs containing fewer than 50 files
- No support for binary file diffs

## Future Enhancements

- [ ] Direct GitHub PR integration via API
- [ ] More sophisticated AST-based relationship detection
- [ ] Syntax highlighting for code (using highlight.js)
- [ ] Comment/annotation system
- [ ] Diff statistics dashboard
- [ ] Support for multiple diff formats

## License

MIT
