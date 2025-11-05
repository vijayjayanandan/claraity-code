#!/usr/bin/env python3
"""
Generate ClarAIty Unified Interface
A comprehensive single-page application for codebase visualization
"""

import json
from pathlib import Path

def load_data():
    """Load unified data."""
    with open('clarity-unified-data.json', 'r', encoding='utf-8') as f:
        return json.load(f)

def generate_html(data):
    """Generate complete HTML with embedded data and visualization."""

    # Escape data for JavaScript embedding
    data_json = json.dumps(data, indent=2)

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ClarAIty - {data["project"]["name"]}</title>
    <script type="text/javascript" src="https://unpkg.com/vis-network@9.1.2/standalone/umd/vis-network.min.js"></script>
    <style>
        {generate_css()}
    </style>
</head>
<body>
    <div class="app-container">
        {generate_header(data)}
        {generate_tabs()}
        {generate_tab_content()}
    </div>

    <script>
        // Embedded unified data
        const clarityData = {data_json};

        {generate_javascript()}
    </script>
</body>
</html>
'''
    return html

def generate_css():
    """Generate complete CSS for all views."""
    return '''
        /* ========== GLOBAL STYLES ========== */
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: #333;
            overflow-x: hidden;
        }

        .app-container {
            max-width: 1920px;
            margin: 0 auto;
            min-height: 100vh;
            padding: 20px;
        }

        /* ========== HEADER ========== */
        .header {
            background: white;
            border-radius: 10px;
            padding: 30px;
            margin-bottom: 20px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.15);
        }

        .header h1 {
            color: #667eea;
            font-size: 2.5em;
            margin-bottom: 10px;
        }

        .header p {
            color: #666;
            font-size: 1.1em;
        }

        .quick-stats {
            display: flex;
            gap: 15px;
            margin-top: 20px;
            flex-wrap: wrap;
        }

        .stat-badge {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 8px 16px;
            border-radius: 20px;
            font-size: 0.9em;
            font-weight: 500;
        }

        /* ========== TABS ========== */
        .tabs {
            background: white;
            border-radius: 10px 10px 0 0;
            padding: 0;
            box-shadow: 0 5px 20px rgba(0,0,0,0.1);
            overflow-x: auto;
        }

        .tab-buttons {
            display: flex;
            gap: 0;
            border-bottom: 2px solid #eee;
        }

        .tab-button {
            padding: 18px 30px;
            background: transparent;
            border: none;
            cursor: pointer;
            font-size: 1em;
            font-weight: 500;
            color: #666;
            transition: all 0.3s ease;
            white-space: nowrap;
            border-bottom: 3px solid transparent;
        }

        .tab-button:hover {
            background: #f8f9fa;
            color: #667eea;
        }

        .tab-button.active {
            color: #667eea;
            border-bottom-color: #667eea;
            background: #f8f9fa;
        }

        .tab-button .icon {
            margin-right: 8px;
            font-size: 1.2em;
        }

        /* ========== TAB CONTENT ========== */
        .tab-content {
            background: white;
            border-radius: 0 0 10px 10px;
            min-height: 600px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.1);
        }

        .tab-pane {
            display: none;
            padding: 40px;
            animation: fadeIn 0.3s ease-in;
        }

        .tab-pane.active {
            display: block;
        }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }

        /* ========== DASHBOARD STYLES ========== */
        .dashboard-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }

        .capability-card {
            background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
            border-left: 5px solid #667eea;
            border-radius: 8px;
            padding: 20px;
            transition: all 0.3s ease;
            cursor: pointer;
        }

        .capability-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 10px 30px rgba(0,0,0,0.15);
        }

        .capability-card h3 {
            color: #333;
            font-size: 1.3em;
            margin-bottom: 10px;
        }

        .capability-card p {
            color: #666;
            font-size: 0.95em;
            margin-bottom: 15px;
        }

        .readiness-bar {
            background: #e9ecef;
            height: 8px;
            border-radius: 10px;
            overflow: hidden;
            margin: 10px 0;
        }

        .readiness-fill {
            background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
            height: 100%;
            transition: width 0.5s ease;
        }

        .readiness-label {
            font-size: 0.85em;
            color: #666;
            margin-top: 5px;
        }

        .component-pills {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-top: 10px;
        }

        .component-pill {
            background: white;
            padding: 5px 12px;
            border-radius: 15px;
            font-size: 0.85em;
            color: #667eea;
            font-weight: 500;
        }

        .entry-points {
            background: #e8f5e9;
            border-left: 5px solid #4caf50;
            padding: 20px;
            border-radius: 8px;
            margin-top: 20px;
        }

        .entry-point {
            padding: 12px;
            background: white;
            border-radius: 5px;
            margin-bottom: 10px;
        }

        .entry-point:last-child {
            margin-bottom: 0;
        }

        .code-ref {
            font-family: 'Courier New', monospace;
            color: #667eea;
            font-weight: 500;
            font-size: 0.9em;
        }

        /* ========== ARCHITECTURE STYLES ========== */
        #architecture-network {
            width: 100%;
            height: 700px;
            border: 2px solid #eee;
            border-radius: 8px;
        }

        .legend {
            display: flex;
            flex-wrap: wrap;
            gap: 15px;
            margin-top: 20px;
            padding: 20px;
            background: #f8f9fa;
            border-radius: 8px;
        }

        .legend-item {
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .legend-color {
            width: 20px;
            height: 20px;
            border-radius: 4px;
        }

        /* ========== FLOW STYLES (from flow-viz) ========== */
        .timeline {
            position: relative;
            padding-left: 60px;
        }

        .timeline::before {
            content: '';
            position: absolute;
            left: 30px;
            top: 0;
            bottom: 0;
            width: 3px;
            background: linear-gradient(180deg, #667eea 0%, #764ba2 100%);
        }

        .step {
            position: relative;
            margin-bottom: 30px;
        }

        .step-marker {
            position: absolute;
            left: -45px;
            width: 30px;
            height: 30px;
            border-radius: 50%;
            background: white;
            border: 4px solid #667eea;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: bold;
            color: #667eea;
            font-size: 0.8em;
            z-index: 10;
        }

        .step-marker.critical {
            background: #ff6b6b;
            border-color: #ff6b6b;
            color: white;
            box-shadow: 0 0 0 4px rgba(255, 107, 107, 0.2);
        }

        .step-marker.decision {
            width: 40px;
            height: 40px;
            border-radius: 0;
            transform: rotate(45deg);
            background: #f39c12;
            border-color: #f39c12;
        }

        .step-marker.decision span {
            transform: rotate(-45deg);
            color: white;
        }

        .step-card {
            background: #f8f9fa;
            border-left: 4px solid #667eea;
            border-radius: 8px;
            padding: 20px;
            transition: all 0.3s ease;
            cursor: pointer;
        }

        .step-card:hover {
            background: #fff;
            box-shadow: 0 5px 20px rgba(0,0,0,0.1);
            transform: translateX(5px);
        }

        .step-card.decision {
            border-left-color: #f39c12;
        }

        .step-card.critical {
            border-left-color: #ff6b6b;
        }

        .step-title {
            font-size: 1.3em;
            color: #333;
            margin-bottom: 10px;
            font-weight: 600;
        }

        .step-description {
            color: #666;
            line-height: 1.6;
            margin-bottom: 15px;
        }

        .substeps {
            margin-top: 20px;
            padding-left: 40px;
            border-left: 2px dashed #ccc;
            display: none;
        }

        .substeps.expanded {
            display: block;
        }

        .expand-toggle {
            display: inline-block;
            padding: 8px 15px;
            background: #667eea;
            color: white;
            border-radius: 5px;
            cursor: pointer;
            font-size: 0.9em;
            margin-top: 10px;
            transition: background 0.3s ease;
        }

        .expand-toggle:hover {
            background: #764ba2;
        }

        .expand-toggle::before {
            content: '▶ ';
        }

        .expand-toggle.expanded::before {
            content: '▼ ';
        }

        /* ========== FILES STYLES ========== */
        .files-layout {
            display: grid;
            grid-template-columns: 350px 1fr;
            gap: 20px;
            height: 700px;
        }

        .file-tree {
            background: #f8f9fa;
            border-radius: 8px;
            padding: 20px;
            overflow-y: auto;
        }

        .file-details {
            background: #f8f9fa;
            border-radius: 8px;
            padding: 20px;
            overflow-y: auto;
        }

        .tree-node {
            margin-left: 15px;
            margin-top: 5px;
        }

        .tree-item {
            padding: 8px 12px;
            cursor: pointer;
            border-radius: 5px;
            transition: background 0.2s ease;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .tree-item:hover {
            background: rgba(102, 126, 234, 0.1);
        }

        .tree-item.selected {
            background: #667eea;
            color: white;
        }

        .tree-item .icon {
            font-size: 1em;
        }

        .tree-toggle {
            cursor: pointer;
            display: inline-block;
            width: 20px;
            text-align: center;
        }

        /* ========== SEARCH STYLES ========== */
        .search-box {
            margin-bottom: 30px;
        }

        .search-input {
            width: 100%;
            padding: 15px 20px;
            font-size: 1.1em;
            border: 2px solid #eee;
            border-radius: 8px;
            transition: border-color 0.3s ease;
        }

        .search-input:focus {
            outline: none;
            border-color: #667eea;
        }

        .search-results {
            margin-top: 20px;
        }

        .search-result {
            background: #f8f9fa;
            border-left: 4px solid #667eea;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 15px;
            cursor: pointer;
            transition: all 0.3s ease;
        }

        .search-result:hover {
            background: white;
            box-shadow: 0 5px 20px rgba(0,0,0,0.1);
        }

        .result-type {
            display: inline-block;
            padding: 4px 12px;
            background: #667eea;
            color: white;
            border-radius: 15px;
            font-size: 0.85em;
            margin-bottom: 10px;
        }

        .result-title {
            font-size: 1.2em;
            font-weight: 600;
            color: #333;
            margin-bottom: 8px;
        }

        .result-description {
            color: #666;
            line-height: 1.6;
        }

        /* ========== UTILITY CLASSES ========== */
        .layer-core { color: #c62828; }
        .layer-workflow { color: #2e7d32; }
        .layer-memory { color: #00695c; }
        .layer-tools { color: #e65100; }
        .layer-rag { color: #1565c0; }

        .badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 15px;
            font-size: 0.85em;
            font-weight: 500;
        }

        .badge-core { background: #ffebee; color: #c62828; }
        .badge-workflow { background: #e8f5e9; color: #2e7d32; }
        .badge-memory { background: #e0f2f1; color: #00695c; }
        .badge-tools { background: #fff3e0; color: #e65100; }
        .badge-rag { background: #e3f2fd; color: #1565c0; }

        /* ========== RESPONSIVE ========== */
        @media (max-width: 1200px) {
            .files-layout {
                grid-template-columns: 1fr;
                height: auto;
            }

            .file-tree, .file-details {
                height: 400px;
            }
        }

        @media (max-width: 768px) {
            .header h1 {
                font-size: 1.8em;
            }

            .tab-button {
                padding: 15px 20px;
                font-size: 0.9em;
            }

            .dashboard-grid {
                grid-template-columns: 1fr;
            }
        }
    '''

def generate_header(data):
    """Generate header section."""
    proj = data['project']
    stats = data['stats']

    return f'''
        <div class="header">
            <h1>🤖 {proj["name"]} - ClarAIty</h1>
            <p>{proj["description"]}</p>
            <div class="quick-stats">
                <span class="stat-badge">📦 {stats["components"]} Components</span>
                <span class="stat-badge">📄 {stats["files"]} Files</span>
                <span class="stat-badge">🔗 {stats["relationships"]} Relationships</span>
                <span class="stat-badge">🔄 {stats["flows"]} Flows</span>
                <span class="stat-badge">🏗️ {stats["layers"]} Layers</span>
            </div>
        </div>
    '''

def generate_tabs():
    """Generate tab navigation."""
    return '''
        <div class="tabs">
            <div class="tab-buttons">
                <button class="tab-button active" onclick="switchTab('dashboard')">
                    <span class="icon">🏠</span> Dashboard
                </button>
                <button class="tab-button" onclick="switchTab('architecture')">
                    <span class="icon">🏗️</span> Architecture
                </button>
                <button class="tab-button" onclick="switchTab('flows')">
                    <span class="icon">🔄</span> Flows
                </button>
                <button class="tab-button" onclick="switchTab('files')">
                    <span class="icon">📁</span> Files
                </button>
                <button class="tab-button" onclick="switchTab('search')">
                    <span class="icon">🔍</span> Search
                </button>
            </div>
        </div>
    '''

def generate_tab_content():
    """Generate all tab content containers."""
    return '''
        <div class="tab-content">
            <div id="dashboard-pane" class="tab-pane active"></div>
            <div id="architecture-pane" class="tab-pane"></div>
            <div id="flows-pane" class="tab-pane"></div>
            <div id="files-pane" class="tab-pane"></div>
            <div id="search-pane" class="tab-pane"></div>
        </div>
    '''

def generate_javascript():
    """Generate all JavaScript code."""
    return '''
        /* ========== GLOBAL STATE ========== */
        let currentTab = 'dashboard';
        let architectureNetwork = null;
        let selectedComponent = null;
        let selectedFile = null;

        /* ========== TAB SWITCHING ========== */
        function switchTab(tabName) {
            // Update buttons
            document.querySelectorAll('.tab-button').forEach(btn => {
                btn.classList.remove('active');
            });
            event.target.closest('.tab-button').classList.add('active');

            // Update panes
            document.querySelectorAll('.tab-pane').forEach(pane => {
                pane.classList.remove('active');
            });
            document.getElementById(tabName + '-pane').classList.add('active');

            currentTab = tabName;

            // Render tab content if not already rendered
            if (tabName === 'dashboard' && !document.getElementById('dashboard-pane').hasChildNodes()) {
                renderDashboard();
            } else if (tabName === 'architecture' && !architectureNetwork) {
                renderArchitecture();
            } else if (tabName === 'flows' && !document.getElementById('flows-pane').hasChildNodes()) {
                renderFlows();
            } else if (tabName === 'files' && !document.getElementById('files-pane').hasChildNodes()) {
                renderFiles();
            } else if (tabName === 'search' && !document.getElementById('search-pane').hasChildNodes()) {
                renderSearch();
            }
        }

        /* ========== DASHBOARD ========== */
        function renderDashboard() {
            const pane = document.getElementById('dashboard-pane');

            let html = '<h2 style="margin-bottom: 30px;">🎯 System Capabilities</h2>';
            html += '<div class="dashboard-grid">';

            clarityData.capabilities.forEach(cap => {
                html += `
                    <div class="capability-card" onclick="navigateToCapability('${cap.layer}')">
                        <h3>${cap.name}</h3>
                        <p>${cap.description}</p>
                        <div class="readiness-bar">
                            <div class="readiness-fill" style="width: ${cap.readiness}%"></div>
                        </div>
                        <div class="readiness-label">${cap.readiness}% Ready</div>
                        <div class="component-pills">
                            ${cap.components.map(c => `<span class="component-pill">${c}</span>`).join('')}
                        </div>
                    </div>
                `;
            });

            html += '</div>';

            // Entry points
            html += '<div class="entry-points">';
            html += '<h3 style="margin-bottom: 15px;">🚀 Entry Points</h3>';
            clarityData.entry_points.forEach(ep => {
                html += `
                    <div class="entry-point">
                        <div style="font-weight: 600; margin-bottom: 5px;">${ep.name}</div>
                        <div style="color: #666; font-size: 0.9em; margin-bottom: 5px;">${ep.description}</div>
                        <div class="code-ref">📁 ${ep.file}:${ep.line}</div>
                    </div>
                `;
            });
            html += '</div>';

            pane.innerHTML = html;
        }

        function navigateToCapability(layer) {
            // Switch to architecture tab and filter by layer
            switchTab('architecture');
            setTimeout(() => {
                if (architectureNetwork) {
                    // Filter network to show only components in this layer
                    const layerComponents = clarityData.components
                        .filter(c => c.layer === layer)
                        .map(c => c.id);
                    architectureNetwork.selectNodes(layerComponents);
                    architectureNetwork.fit({ nodes: layerComponents });
                }
            }, 100);
        }

        /* ========== ARCHITECTURE ========== */
        function renderArchitecture() {
            const pane = document.getElementById('architecture-pane');

            pane.innerHTML = `
                <h2 style="margin-bottom: 20px;">🏗️ System Architecture</h2>
                <div id="architecture-network"></div>
                <div class="legend">
                    <div class="legend-item">
                        <div class="legend-color" style="background: #ef5350;"></div>
                        <span>Core</span>
                    </div>
                    <div class="legend-item">
                        <div class="legend-color" style="background: #66bb6a;"></div>
                        <span>Workflow</span>
                    </div>
                    <div class="legend-item">
                        <div class="legend-color" style="background: #26a69a;"></div>
                        <span>Memory</span>
                    </div>
                    <div class="legend-item">
                        <div class="legend-color" style="background: #ffa726;"></div>
                        <span>Tools</span>
                    </div>
                    <div class="legend-item">
                        <div class="legend-color" style="background: #42a5f5;"></div>
                        <span>RAG</span>
                    </div>
                </div>
            `;

            createArchitectureNetwork();
        }

        function createArchitectureNetwork() {
            const container = document.getElementById('architecture-network');

            // Layer colors
            const layerColors = {
                'core': '#ef5350',
                'workflow': '#66bb6a',
                'memory': '#26a69a',
                'tools': '#ffa726',
                'rag': '#42a5f5',
                'llm': '#ab47bc',
                'prompts': '#7e57c2',
                'hooks': '#ec407a',
                'subagents': '#29b6f6',
                'clarity': '#5c6bc0'
            };

            // Create nodes
            const nodes = clarityData.components.map(comp => ({
                id: comp.id,
                label: comp.name,
                color: layerColors[comp.layer] || '#999',
                shape: comp.type === 'orchestrator' ? 'box' : 'dot',
                size: comp.type === 'orchestrator' ? 30 : 20,
                title: `${comp.name}\\n${comp.purpose || ''}`,
                font: { size: 14, color: '#333' }
            }));

            // Create edges
            const edges = clarityData.relationships.map(rel => ({
                from: rel.source_id,
                to: rel.target_id,
                arrows: 'to',
                title: rel.description,
                width: rel.criticality === 'high' ? 3 : rel.criticality === 'medium' ? 2 : 1,
                color: { opacity: 0.6 }
            }));

            const data = { nodes, edges };

            const options = {
                layout: {
                    hierarchical: {
                        enabled: true,
                        direction: 'UD',
                        sortMethod: 'directed',
                        levelSeparation: 200,
                        nodeSpacing: 150
                    }
                },
                physics: {
                    enabled: false
                },
                interaction: {
                    hover: true,
                    navigationButtons: true
                }
            };

            architectureNetwork = new vis.Network(container, data, options);

            architectureNetwork.on('click', function(params) {
                if (params.nodes.length > 0) {
                    const nodeId = params.nodes[0];
                    selectedComponent = clarityData.components.find(c => c.id === nodeId);
                    showComponentDetails(selectedComponent);
                }
            });
        }

        function showComponentDetails(comp) {
            alert(`Component: ${comp.name}\\n\\nPurpose: ${comp.purpose}\\n\\nLayer: ${comp.layer}\\n\\nType: ${comp.type}`);
        }

        /* ========== FLOWS ========== */
        function renderFlows() {
            const pane = document.getElementById('flows-pane');

            let html = '<h2 style="margin-bottom: 30px;">🔄 Execution Flows</h2>';

            clarityData.flows.forEach(flow => {
                html += `
                    <div style="background: #f8f9fa; padding: 30px; border-radius: 8px; margin-bottom: 20px;">
                        <h3 style="margin-bottom: 10px;">${flow.is_primary ? '⭐ ' : ''}${flow.name}</h3>
                        <p style="color: #666; margin-bottom: 15px;">${flow.description}</p>
                        <div style="color: #667eea; margin-bottom: 20px;">🎯 Trigger: ${flow.trigger}</div>
                        <div class="timeline">
                            ${flow.steps.map((step, i) => renderFlowStep(step, i + 1)).join('')}
                        </div>
                    </div>
                `;
            });

            pane.innerHTML = html;
        }

        function renderFlowStep(step, number) {
            const markerClass = step.is_critical ? 'critical' : step.step_type === 'decision' ? 'decision' : '';
            const cardClass = step.is_critical ? 'critical' : step.step_type === 'decision' ? 'decision' : '';

            let html = `
                <div class="step">
                    <div class="step-marker ${markerClass}">
                        <span>${number}</span>
                    </div>
                    <div class="step-card ${cardClass}">
                        <div class="step-title">${step.title}</div>
                        <div class="step-description">${step.description}</div>
            `;

            if (step.file_path) {
                html += `<div class="code-ref">📁 ${step.file_path}:${step.line_start || ''}</div>`;
            }

            if (step.substeps && step.substeps.length > 0) {
                html += `
                    <div class="expand-toggle" onclick="toggleSubsteps('substeps-${step.id}', this)">
                        Show ${step.substeps.length} substeps
                    </div>
                    <div class="substeps" id="substeps-${step.id}">
                        ${step.substeps.map(sub => renderSubstep(sub)).join('')}
                    </div>
                `;
            }

            html += `</div></div>`;
            return html;
        }

        function renderSubstep(substep) {
            return `
                <div style="background: white; padding: 15px; border-left: 3px solid #17a2b8; border-radius: 5px; margin-bottom: 10px;">
                    <div style="font-weight: 600; color: #17a2b8; margin-bottom: 8px;">${substep.title}</div>
                    <div style="color: #666; font-size: 0.9em;">${substep.description}</div>
                    ${substep.file_path ? `<div class="code-ref" style="margin-top: 8px;">📁 ${substep.file_path}:${substep.line_start || ''}</div>` : ''}
                </div>
            `;
        }

        function toggleSubsteps(id, toggleEl) {
            const substeps = document.getElementById(id);
            substeps.classList.toggle('expanded');
            toggleEl.classList.toggle('expanded');

            if (substeps.classList.contains('expanded')) {
                toggleEl.textContent = toggleEl.textContent.replace('Show', 'Hide');
            } else {
                toggleEl.textContent = toggleEl.textContent.replace('Hide', 'Show');
            }
        }

        /* ========== FILES ========== */
        function renderFiles() {
            const pane = document.getElementById('files-pane');

            pane.innerHTML = `
                <h2 style="margin-bottom: 20px;">📁 Codebase Structure</h2>
                <div class="files-layout">
                    <div class="file-tree" id="file-tree"></div>
                    <div class="file-details" id="file-details">
                        <div style="text-align: center; padding: 50px; color: #999;">
                            Select a file to view details
                        </div>
                    </div>
                </div>
            `;

            renderFileTree();
        }

        function renderFileTree() {
            const container = document.getElementById('file-tree');
            container.innerHTML = renderTreeNode(clarityData.file_tree, '');
        }

        function renderTreeNode(node, path) {
            if (!node) return '';

            let html = '';

            for (const [name, child] of Object.entries(node)) {
                if (name.startsWith('_')) continue;

                const fullPath = path ? `${path}/${name}` : name;

                if (child._type === 'dir') {
                    const stats = child._stats || {};
                    html += `
                        <div class="tree-node">
                            <div class="tree-item" onclick="toggleTreeNode('tree-${fullPath.replace(/[\/\.]/g, '-')}')">
                                <span class="tree-toggle" id="toggle-tree-${fullPath.replace(/[\/\.]/g, '-')}">▶</span>
                                <span class="icon">📁</span>
                                <span>${name}/</span>
                                <span style="margin-left: auto; color: #999; font-size: 0.85em;">${stats.files || 0} files</span>
                            </div>
                            <div id="tree-${fullPath.replace(/[\/\.]/g, '-')}" style="display: none;">
                                ${child._children ? renderTreeNode(child._children, fullPath) : ''}
                            </div>
                        </div>
                    `;
                } else if (child._type === 'file') {
                    html += `
                        <div class="tree-node">
                            <div class="tree-item" onclick="selectFile('${child.path}')">
                                <span style="width: 20px;"></span>
                                <span class="icon">📄</span>
                                <span>${name}</span>
                            </div>
                        </div>
                    `;
                }
            }

            return html;
        }

        function toggleTreeNode(id) {
            const node = document.getElementById(id);
            const toggle = document.getElementById('toggle-' + id);

            if (node.style.display === 'none') {
                node.style.display = 'block';
                toggle.textContent = '▼';
            } else {
                node.style.display = 'none';
                toggle.textContent = '▶';
            }
        }

        function selectFile(filePath) {
            // Find file data
            const file = findFileInTree(clarityData.file_tree, filePath);

            if (file) {
                const detailsPane = document.getElementById('file-details');
                detailsPane.innerHTML = `
                    <h3>${filePath.split('/').pop()}</h3>
                    <div class="code-ref" style="margin-bottom: 20px;">${filePath}</div>

                    <div style="display: flex; gap: 15px; margin-bottom: 20px;">
                        <div class="badge">📊 ${file.line_count} lines</div>
                        <div class="badge">🔧 ${file.artifact_count} artifacts</div>
                    </div>

                    ${file.components.length > 0 ? `
                        <div style="margin-bottom: 20px;">
                            <h4 style="margin-bottom: 10px;">Components:</h4>
                            ${file.components.map(c => `<span class="component-pill">${c}</span>`).join(' ')}
                        </div>
                    ` : ''}

                    ${file.layers.length > 0 ? `
                        <div style="margin-bottom: 20px;">
                            <h4 style="margin-bottom: 10px;">Layers:</h4>
                            ${file.layers.map(l => `<span class="badge badge-${l}">${l}</span>`).join(' ')}
                        </div>
                    ` : ''}

                    <div>
                        <h4 style="margin-bottom: 10px;">Artifacts (${file.artifacts.length}):</h4>
                        ${file.artifacts.slice(0, 10).map(a => `
                            <div style="padding: 10px; background: white; border-radius: 5px; margin-bottom: 8px;">
                                <div style="font-weight: 600;">${a.type}: ${a.name}</div>
                                ${a.description ? `<div style="color: #666; font-size: 0.9em;">${a.description}</div>` : ''}
                                ${a.line_start ? `<div class="code-ref" style="margin-top: 5px;">Lines: ${a.line_start}-${a.line_end}</div>` : ''}
                            </div>
                        `).join('')}
                        ${file.artifacts.length > 10 ? `<div style="color: #999; font-style: italic;">...and ${file.artifacts.length - 10} more</div>` : ''}
                    </div>
                `;
            }
        }

        function findFileInTree(node, targetPath) {
            for (const [name, child] of Object.entries(node)) {
                if (name.startsWith('_')) continue;

                if (child._type === 'file' && child.path === targetPath) {
                    return child;
                }

                if (child._type === 'dir' && child._children) {
                    const found = findFileInTree(child._children, targetPath);
                    if (found) return found;
                }
            }
            return null;
        }

        /* ========== SEARCH ========== */
        function renderSearch() {
            const pane = document.getElementById('search-pane');

            pane.innerHTML = `
                <h2 style="margin-bottom: 30px;">🔍 Search Everything</h2>
                <div class="search-box">
                    <input type="text" class="search-input" id="search-input"
                           placeholder="Search components, files, functions, flows..."
                           oninput="performSearch(this.value)">
                </div>
                <div id="search-results"></div>
            `;
        }

        function performSearch(query) {
            if (!query || query.length < 2) {
                document.getElementById('search-results').innerHTML = '';
                return;
            }

            query = query.toLowerCase();
            const results = [];

            // Search components
            clarityData.components.forEach(comp => {
                if (comp.name.toLowerCase().includes(query) ||
                    (comp.purpose && comp.purpose.toLowerCase().includes(query))) {
                    results.push({
                        type: 'Component',
                        title: comp.name,
                        description: comp.purpose,
                        layer: comp.layer,
                        action: () => {
                            switchTab('architecture');
                            setTimeout(() => {
                                if (architectureNetwork) {
                                    architectureNetwork.selectNodes([comp.id]);
                                    architectureNetwork.focus(comp.id);
                                }
                            }, 100);
                        }
                    });
                }
            });

            // Search artifacts
            clarityData.artifacts.forEach(art => {
                if (art.name.toLowerCase().includes(query) ||
                    (art.description && art.description.toLowerCase().includes(query))) {
                    results.push({
                        type: 'Artifact',
                        title: `${art.type}: ${art.name}`,
                        description: art.description || `In ${art.file_path}`,
                        file: art.file_path,
                        action: () => {
                            switchTab('files');
                            setTimeout(() => selectFile(art.file_path), 100);
                        }
                    });
                }
            });

            // Search flows
            clarityData.flows.forEach(flow => {
                flow.steps.forEach(step => {
                    if (step.title.toLowerCase().includes(query) ||
                        step.description.toLowerCase().includes(query)) {
                        results.push({
                            type: 'Flow Step',
                            title: `${flow.name}: ${step.title}`,
                            description: step.description,
                            file: step.file_path,
                            action: () => switchTab('flows')
                        });
                    }
                });
            });

            displaySearchResults(results);
        }

        function displaySearchResults(results) {
            const container = document.getElementById('search-results');

            if (results.length === 0) {
                container.innerHTML = '<div style="text-align: center; padding: 50px; color: #999;">No results found</div>';
                return;
            }

            let html = `<div style="margin-bottom: 15px; color: #666;">Found ${results.length} results</div>`;

            results.slice(0, 20).forEach(result => {
                html += `
                    <div class="search-result" onclick="searchResultClicked(${results.indexOf(result)})">
                        <span class="result-type">${result.type}</span>
                        <div class="result-title">${result.title}</div>
                        <div class="result-description">${result.description || ''}</div>
                        ${result.file ? `<div class="code-ref" style="margin-top: 10px;">📁 ${result.file}</div>` : ''}
                        ${result.layer ? `<span class="badge badge-${result.layer}">${result.layer}</span>` : ''}
                    </div>
                `;
            });

            if (results.length > 20) {
                html += `<div style="text-align: center; color: #999; margin-top: 20px;">...and ${results.length - 20} more results</div>`;
            }

            container.innerHTML = html;

            // Store results for click handling
            window.searchResults = results;
        }

        function searchResultClicked(index) {
            const result = window.searchResults[index];
            if (result.action) {
                result.action();
            }
        }

        /* ========== INITIALIZATION ========== */
        document.addEventListener('DOMContentLoaded', function() {
            renderDashboard();
        });
    '''

def main():
    """Main generator function."""
    print("🔧 Generating ClarAIty Unified Interface...")

    data = load_data()
    html = generate_html(data)

    output_path = Path('clarity-unified.html')
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    file_size = output_path.stat().st_size / 1024
    print(f"✅ Created {output_path}")
    print(f"📦 File size: {file_size:.1f} KB")
    print(f"\n🚀 Open {output_path} in your browser!")

if __name__ == "__main__":
    main()
