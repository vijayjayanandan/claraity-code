#!/usr/bin/env python3
"""
Generate ClarAIty Unified Interface v2
With improved 3-level capability-based Architecture view
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
    """Generate complete CSS including new Architecture styles."""
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

        /* ========== NEW ARCHITECTURE STYLES ========== */
        .architecture-view {
            position: relative;
        }

        .arch-level-1 {
            display: block;
        }

        .arch-level-2 {
            display: none;
        }

        .arch-level-2.active {
            display: block;
            animation: slideIn 0.3s ease-out;
        }

        @keyframes slideIn {
            from {
                opacity: 0;
                transform: translateX(-20px);
            }
            to {
                opacity: 1;
                transform: translateX(0);
            }
        }

        .arch-capability-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 25px;
            margin-top: 30px;
        }

        .arch-capability-card {
            background: white;
            border-radius: 12px;
            padding: 30px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.08);
            transition: all 0.3s ease;
            cursor: pointer;
            position: relative;
            overflow: hidden;
        }

        .arch-capability-card::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 5px;
            height: 100%;
            background: linear-gradient(180deg, #667eea 0%, #764ba2 100%);
        }

        .arch-capability-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 10px 30px rgba(0,0,0,0.15);
        }

        .arch-card-header {
            display: flex;
            align-items: center;
            gap: 15px;
            margin-bottom: 15px;
        }

        .arch-card-icon {
            font-size: 2.5em;
            line-height: 1;
        }

        .arch-card-title {
            flex: 1;
        }

        .arch-card-title h3 {
            color: #333;
            font-size: 1.4em;
            margin-bottom: 5px;
        }

        .arch-card-title .subtitle {
            color: #999;
            font-size: 0.85em;
        }

        .arch-card-description {
            color: #666;
            line-height: 1.6;
            margin-bottom: 20px;
            font-size: 0.95em;
        }

        .arch-readiness {
            margin-bottom: 15px;
        }

        .arch-readiness-bar {
            background: #f0f0f0;
            height: 10px;
            border-radius: 10px;
            overflow: hidden;
            margin: 8px 0;
        }

        .arch-readiness-fill {
            height: 100%;
            border-radius: 10px;
            transition: width 0.5s ease;
        }

        .readiness-high {
            background: linear-gradient(90deg, #4caf50 0%, #66bb6a 100%);
        }

        .readiness-medium {
            background: linear-gradient(90deg, #ff9800 0%, #ffb74d 100%);
        }

        .readiness-low {
            background: linear-gradient(90deg, #f44336 0%, #ef5350 100%);
        }

        .arch-readiness-label {
            font-size: 0.9em;
            font-weight: 600;
        }

        .arch-components {
            margin-bottom: 20px;
        }

        .arch-components-label {
            font-size: 0.85em;
            color: #999;
            margin-bottom: 8px;
            font-weight: 500;
        }

        .arch-component-tags {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }

        .arch-component-tag {
            background: #f8f9fa;
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 0.85em;
            color: #555;
            border: 1px solid #e9ecef;
        }

        .arch-expand-btn {
            width: 100%;
            padding: 12px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 0.95em;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
        }

        .arch-expand-btn:hover {
            transform: scale(1.02);
            box-shadow: 0 5px 15px rgba(102, 126, 234, 0.3);
        }

        /* ========== EXPANDED VIEW (LEVEL 2) ========== */
        .arch-expanded-view {
            background: white;
            border-radius: 12px;
            padding: 40px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.1);
        }

        .arch-expanded-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 30px;
            padding-bottom: 20px;
            border-bottom: 2px solid #f0f0f0;
        }

        .arch-expanded-title {
            flex: 1;
        }

        .arch-expanded-title h2 {
            color: #333;
            font-size: 2em;
            margin-bottom: 10px;
        }

        .arch-expanded-title p {
            color: #666;
            font-size: 1.1em;
            line-height: 1.6;
        }

        .arch-back-btn {
            padding: 12px 24px;
            background: #f8f9fa;
            color: #667eea;
            border: 2px solid #667eea;
            border-radius: 8px;
            font-size: 0.95em;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
        }

        .arch-back-btn:hover {
            background: #667eea;
            color: white;
        }

        .arch-components-flow {
            background: #f8f9fa;
            border-radius: 10px;
            padding: 30px;
            margin-bottom: 30px;
        }

        .arch-components-flow h3 {
            color: #333;
            font-size: 1.3em;
            margin-bottom: 20px;
        }

        .component-flow-diagram {
            display: flex;
            align-items: center;
            gap: 20px;
            flex-wrap: wrap;
            justify-content: center;
        }

        .flow-component {
            background: white;
            padding: 20px 30px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.08);
            min-width: 150px;
            text-align: center;
            border: 2px solid #667eea;
        }

        .flow-component-name {
            font-weight: 600;
            color: #333;
            font-size: 1.05em;
        }

        .flow-arrow {
            font-size: 1.5em;
            color: #667eea;
        }

        .arch-files-section {
            background: #fff3e0;
            border-radius: 10px;
            padding: 25px;
            margin-bottom: 30px;
        }

        .arch-files-section h3 {
            color: #333;
            font-size: 1.3em;
            margin-bottom: 15px;
        }

        .file-list {
            display: flex;
            flex-direction: column;
            gap: 12px;
        }

        .file-item {
            background: white;
            padding: 15px 20px;
            border-radius: 8px;
            display: flex;
            align-items: center;
            gap: 12px;
            cursor: pointer;
            transition: all 0.2s ease;
        }

        .file-item:hover {
            transform: translateX(5px);
            box-shadow: 0 3px 10px rgba(0,0,0,0.1);
        }

        .file-icon {
            font-size: 1.2em;
        }

        .file-path {
            flex: 1;
            font-family: 'Courier New', monospace;
            color: #667eea;
            font-size: 0.95em;
        }

        .file-info {
            color: #999;
            font-size: 0.85em;
        }

        .arch-flows-section {
            background: #e8f5e9;
            border-radius: 10px;
            padding: 25px;
            margin-bottom: 30px;
        }

        .arch-flows-section h3 {
            color: #333;
            font-size: 1.3em;
            margin-bottom: 15px;
        }

        .flow-usage-list {
            display: flex;
            flex-direction: column;
            gap: 10px;
        }

        .flow-usage-item {
            background: white;
            padding: 12px 18px;
            border-radius: 8px;
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .flow-icon {
            font-size: 1.1em;
        }

        .arch-actions {
            display: flex;
            gap: 15px;
            flex-wrap: wrap;
        }

        .action-btn {
            flex: 1;
            min-width: 200px;
            padding: 15px 25px;
            border-radius: 10px;
            font-size: 1em;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            border: none;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
        }

        .action-btn-primary {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }

        .action-btn-primary:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 20px rgba(102, 126, 234, 0.3);
        }

        .action-btn-secondary {
            background: white;
            color: #667eea;
            border: 2px solid #667eea;
        }

        .action-btn-secondary:hover {
            background: #f8f9fa;
        }

        /* ========== FLOW STYLES ========== */
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

            .arch-capability-grid {
                grid-template-columns: 1fr;
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

            .arch-actions {
                flex-direction: column;
            }

            .action-btn {
                min-width: 100%;
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
    """Generate all JavaScript code with new Architecture implementation."""
    # Due to length, I'll split this into a separate file
    # For now, return a placeholder that imports from external file
    return open('clarity_ui_javascript.js', 'r').read() if Path('clarity_ui_javascript.js').exists() else generate_inline_javascript()

def generate_inline_javascript():
    """Generate inline JavaScript (full implementation)."""
    js_code = '''
        /* ========== GLOBAL STATE ========== */
        let currentTab = 'dashboard';
        let selectedCapability = null;
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
            } else if (tabName === 'architecture' && !document.getElementById('architecture-pane').hasChildNodes()) {
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
            switchTab('architecture');
            // Find capability by layer and expand it
            setTimeout(() => {
                const capability = clarityData.capabilities.find(c => c.layer === layer);
                if (capability) {
                    showCapabilityDetails(capability);
                }
            }, 100);
        }

        /* ========== NEW ARCHITECTURE (3-LEVEL VIEW) ========== */
        function renderArchitecture() {
            const pane = document.getElementById('architecture-pane');

            pane.innerHTML = `
                <div class="architecture-view">
                    <div class="arch-level-1" id="arch-level-1">
                        <h2 style="margin-bottom: 10px;">🏗️ System Architecture</h2>
                        <p style="color: #666; margin-bottom: 30px; font-size: 1.05em;">
                            Capability-based architecture organized by business value and technical concerns
                        </p>
                        <div class="arch-capability-grid" id="arch-capability-grid"></div>
                    </div>
                    <div class="arch-level-2" id="arch-level-2"></div>
                </div>
            `;

            renderCapabilityCards();
        }

        function renderCapabilityCards() {
            const container = document.getElementById('arch-capability-grid');

            let html = '';
            clarityData.capabilities.forEach((cap, index) => {
                const readinessClass = cap.readiness >= 90 ? 'readiness-high' :
                                      cap.readiness >= 70 ? 'readiness-medium' : 'readiness-low';

                const icons = ['📋', '⚙️', '✅', '💾', '🔍'];
                const icon = icons[index] || '📦';

                html += `
                    <div class="arch-capability-card">
                        <div class="arch-card-header">
                            <div class="arch-card-icon">${icon}</div>
                            <div class="arch-card-title">
                                <h3>${cap.name}</h3>
                                <div class="subtitle">${cap.components.length} Components</div>
                            </div>
                        </div>

                        <div class="arch-card-description">
                            ${cap.description}
                        </div>

                        <div class="arch-readiness">
                            <div class="arch-readiness-bar">
                                <div class="arch-readiness-fill ${readinessClass}" style="width: ${cap.readiness}%"></div>
                            </div>
                            <div class="arch-readiness-label">${cap.readiness}% Production Ready</div>
                        </div>

                        <div class="arch-components">
                            <div class="arch-components-label">KEY COMPONENTS:</div>
                            <div class="arch-component-tags">
                                ${cap.components.slice(0, 4).map(c => `
                                    <span class="arch-component-tag">${c}</span>
                                `).join('')}
                                ${cap.components.length > 4 ? `<span class="arch-component-tag">+${cap.components.length - 4} more</span>` : ''}
                            </div>
                        </div>

                        <button class="arch-expand-btn" onclick='showCapabilityDetails(${JSON.stringify(cap)})'>
                            Expand Details →
                        </button>
                    </div>
                `;
            });

            container.innerHTML = html;
        }

        function showCapabilityDetails(capability) {
            selectedCapability = capability;

            // Hide level 1, show level 2
            document.getElementById('arch-level-1').style.display = 'none';
            document.getElementById('arch-level-2').classList.add('active');

            // Get component details
            const components = clarityData.components.filter(c =>
                capability.components.includes(c.name)
            );

            // Get files for these components
            const componentIds = components.map(c => c.id);
            const files = clarityData.artifacts.filter(a =>
                componentIds.includes(a.component_id)
            ).reduce((acc, artifact) => {
                if (!acc.find(f => f.file_path === artifact.file_path)) {
                    acc.push(artifact);
                }
                return acc;
            }, []);

            // Group files by path
            const uniqueFiles = {};
            files.forEach(f => {
                if (!uniqueFiles[f.file_path]) {
                    uniqueFiles[f.file_path] = f;
                }
            });

            const icons = {'Planning & Analysis': '📋', 'Execution': '⚙️', 'Verification': '✅',
                          'Memory Management': '💾', 'Code Understanding': '🔍'};
            const icon = icons[capability.name] || '📦';

            let html = `
                <div class="arch-expanded-view">
                    <div class="arch-expanded-header">
                        <div class="arch-expanded-title">
                            <h2>${icon} ${capability.name}</h2>
                            <p>${capability.description}</p>
                        </div>
                        <button class="arch-back-btn" onclick="backToArchitectureOverview()">
                            ← Back to Overview
                        </button>
                    </div>

                    <div class="arch-components-flow">
                        <h3>💡 Components & Flow</h3>
                        <div class="component-flow-diagram">
                            ${components.map((comp, idx) => `
                                <div class="flow-component">
                                    <div class="flow-component-name">${comp.name}</div>
                                </div>
                                ${idx < components.length - 1 ? '<div class="flow-arrow">→</div>' : ''}
                            `).join('')}
                        </div>
                    </div>

                    <div class="arch-files-section">
                        <h3>📁 Implementation Files</h3>
                        <div class="file-list">
                            ${Object.values(uniqueFiles).slice(0, 10).map(file => `
                                <div class="file-item" onclick="navigateToFile('${file.file_path}')">
                                    <span class="file-icon">📄</span>
                                    <span class="file-path">${file.file_path}</span>
                                    <span class="file-info">${file.line_end || '~100'} lines</span>
                                </div>
                            `).join('')}
                            ${Object.values(uniqueFiles).length > 10 ?
                                `<div style="color: #999; font-style: italic; padding: 10px;">...and ${Object.values(uniqueFiles).length - 10} more files</div>`
                                : ''}
                        </div>
                    </div>

                    <div class="arch-flows-section">
                        <h3>🔄 Used in Execution Flows</h3>
                        <div class="flow-usage-list">
                            <div class="flow-usage-item">
                                <span class="flow-icon">⚡</span>
                                <span>Workflow Execution Flow - Primary path for complex tasks</span>
                            </div>
                        </div>
                    </div>

                    <div class="arch-actions">
                        <button class="action-btn action-btn-primary" onclick="navigateToFiles()">
                            📁 View All Files
                        </button>
                        <button class="action-btn action-btn-secondary" onclick="navigateToFlows()">
                            🔄 View Execution Flows
                        </button>
                    </div>
                </div>
            `;

            document.getElementById('arch-level-2').innerHTML = html;
        }

        function backToArchitectureOverview() {
            document.getElementById('arch-level-1').style.display = 'block';
            document.getElementById('arch-level-2').classList.remove('active');
            selectedCapability = null;
        }

        function navigateToFile(filePath) {
            switchTab('files');
            setTimeout(() => {
                selectFile(filePath);
            }, 100);
        }

        function navigateToFiles() {
            switchTab('files');
        }

        function navigateToFlows() {
            switchTab('flows');
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
                            <div class="tree-item" onclick="toggleTreeNode('tree-${fullPath.replace(/[\\/\\.]/g, '-')}')">
                                <span class="tree-toggle" id="toggle-tree-${fullPath.replace(/[\\/\\.]/g, '-')}">▶</span>
                                <span class="icon">📁</span>
                                <span>${name}/</span>
                                <span style="margin-left: auto; color: #999; font-size: 0.85em;">${stats.files || 0} files</span>
                            </div>
                            <div id="tree-${fullPath.replace(/[\\/\\.]/g, '-')}" style="display: none;">
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

    return js_code

def main():
    """Main generator function."""
    print("🔧 Generating ClarAIty Unified Interface v2 (with improved Architecture)...")

    data = load_data()
    html = generate_html(data)

    output_path = Path('clarity-unified.html')
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    file_size = output_path.stat().st_size / 1024
    print(f"✅ Created {output_path}")
    print(f"📦 File size: {file_size:.1f} KB")
    print(f"\n🎯 Key Improvements:")
    print(f"   - ✅ Removed vis.js dependency (no more dots!)")
    print(f"   - ✅ 3-level capability-based Architecture view")
    print(f"   - ✅ Professional capability cards with readiness bars")
    print(f"   - ✅ Expandable component details with flow diagrams")
    print(f"   - ✅ Cross-navigation to Files and Flows tabs")
    print(f"\n🚀 Open {output_path} in your browser!")

if __name__ == "__main__":
    main()
