# ClarAIty UI

Interactive architecture visualization for the AI Coding Agent.

## Features

- **Interactive Architecture Diagram** - Visualize components using React Flow
- **Component Details** - Explore component information, artifacts, decisions, and relationships
- **Layer-based Organization** - Components organized by architectural layer
- **Real-time Updates** - WebSocket support for live generation updates (future)

## Getting Started

### Prerequisites

- Node.js 18+
- npm or yarn
- ClarAIty API running on `http://localhost:8000`

### Installation

```bash
cd clarity-ui
npm install
```

### Development

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

### Build

```bash
npm run build
npm run preview
```

## Project Structure

```
clarity-ui/
├── src/
│   ├── components/
│   │   ├── ArchitectureDiagram.tsx  # Main visualization component
│   │   ├── ComponentNode.tsx        # Custom React Flow node
│   │   └── ComponentDetails.tsx     # Detail panel
│   ├── services/
│   │   └── api.ts                   # API client
│   ├── types/
│   │   └── index.ts                 # TypeScript definitions
│   ├── App.tsx                      # Main application
│   ├── main.tsx                     # Entry point
│   └── index.css                    # Global styles
├── package.json
├── tsconfig.json
├── vite.config.ts
└── index.html
```

## Architecture

The UI connects to the ClarAIty FastAPI backend to:

1. Load architecture summary (`/architecture`)
2. Fetch all components (`/components`)
3. Get component relationships (`/relationships`)
4. Retrieve component details (`/components/{id}`)

Components are visualized using React Flow with:
- Custom node rendering (ComponentNode)
- Layer-based layout algorithm
- Color coding by architectural layer
- Click-to-view-details interaction

## Technologies

- **React 18** - UI library
- **TypeScript** - Type safety
- **Vite** - Build tool and dev server
- **React Flow** - Interactive diagrams
- **Material-UI** - Component library
- **Axios** - HTTP client

## API Integration

The UI expects the FastAPI server to be running on `http://localhost:8000`.

To start the backend:

```bash
cd /workspaces/ai-coding-agent
uvicorn src.clarity.api.main:app --reload --port 8000
```

## License

Part of the AI Coding Agent project.
