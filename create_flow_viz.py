#!/usr/bin/env python3
"""Create flow-viz-embedded.html with flow data embedded."""

import json
from pathlib import Path

def create_flow_viz():
    """Generate standalone HTML with embedded flow visualization."""

    # Load flow data
    with open('flow-data.json', 'r', encoding='utf-8') as f:
        flow_data = json.load(f)

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ClarAIty - Execution Flow Visualization</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }}

        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}

        .header {{
            background: white;
            border-radius: 10px;
            padding: 30px;
            margin-bottom: 20px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.1);
        }}

        .header h1 {{
            color: #667eea;
            font-size: 2.5em;
            margin-bottom: 10px;
        }}

        .header p {{
            color: #666;
            font-size: 1.1em;
        }}

        .stats {{
            display: flex;
            gap: 20px;
            margin-top: 20px;
        }}

        .stat-card {{
            flex: 1;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 8px;
            text-align: center;
        }}

        .stat-number {{
            font-size: 2.5em;
            font-weight: bold;
        }}

        .stat-label {{
            font-size: 0.9em;
            opacity: 0.9;
            margin-top: 5px;
        }}

        .flow-container {{
            background: white;
            border-radius: 10px;
            padding: 40px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.1);
        }}

        .flow-header {{
            border-bottom: 2px solid #eee;
            padding-bottom: 20px;
            margin-bottom: 40px;
        }}

        .flow-title {{
            font-size: 2em;
            color: #333;
            margin-bottom: 10px;
        }}

        .flow-trigger {{
            color: #666;
            font-size: 1.1em;
            margin-bottom: 10px;
        }}

        .flow-description {{
            color: #777;
            line-height: 1.6;
        }}

        .complexity-badge {{
            display: inline-block;
            padding: 5px 15px;
            border-radius: 20px;
            font-size: 0.9em;
            margin-top: 10px;
            font-weight: 500;
        }}

        .complexity-complex {{
            background: #ff6b6b;
            color: white;
        }}

        .complexity-medium {{
            background: #f39c12;
            color: white;
        }}

        .complexity-simple {{
            background: #2ecc71;
            color: white;
        }}

        .timeline {{
            position: relative;
            padding-left: 60px;
        }}

        .timeline::before {{
            content: '';
            position: absolute;
            left: 30px;
            top: 0;
            bottom: 0;
            width: 3px;
            background: linear-gradient(180deg, #667eea 0%, #764ba2 100%);
        }}

        .step {{
            position: relative;
            margin-bottom: 30px;
            animation: fadeIn 0.5s ease-in;
        }}

        @keyframes fadeIn {{
            from {{
                opacity: 0;
                transform: translateY(20px);
            }}
            to {{
                opacity: 1;
                transform: translateY(0);
            }}
        }}

        .step-marker {{
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
        }}

        .step-marker.critical {{
            background: #ff6b6b;
            border-color: #ff6b6b;
            color: white;
            box-shadow: 0 0 0 4px rgba(255, 107, 107, 0.2);
        }}

        .step-marker.decision {{
            width: 40px;
            height: 40px;
            border-radius: 0;
            transform: rotate(45deg);
            background: #f39c12;
            border-color: #f39c12;
        }}

        .step-marker.decision span {{
            transform: rotate(-45deg);
            color: white;
        }}

        .step-card {{
            background: #f8f9fa;
            border-left: 4px solid #667eea;
            border-radius: 8px;
            padding: 20px;
            transition: all 0.3s ease;
            cursor: pointer;
        }}

        .step-card:hover {{
            background: #fff;
            box-shadow: 0 5px 20px rgba(0,0,0,0.1);
            transform: translateX(5px);
        }}

        .step-card.decision {{
            border-left-color: #f39c12;
        }}

        .step-card.critical {{
            border-left-color: #ff6b6b;
        }}

        .step-title {{
            font-size: 1.3em;
            color: #333;
            margin-bottom: 10px;
            font-weight: 600;
        }}

        .step-description {{
            color: #666;
            line-height: 1.6;
            margin-bottom: 15px;
        }}

        .step-meta {{
            display: flex;
            gap: 15px;
            flex-wrap: wrap;
            margin-top: 15px;
        }}

        .meta-item {{
            display: flex;
            align-items: center;
            gap: 5px;
            padding: 5px 12px;
            background: white;
            border-radius: 5px;
            font-size: 0.9em;
        }}

        .code-ref {{
            color: #667eea;
            font-family: 'Courier New', monospace;
            font-weight: 500;
        }}

        .component-tag {{
            background: #e3f2fd;
            color: #1976d2;
            padding: 3px 10px;
            border-radius: 4px;
            font-size: 0.85em;
        }}

        .decision-box {{
            background: #fff3cd;
            border-left: 4px solid #f39c12;
            padding: 15px;
            margin-top: 15px;
            border-radius: 5px;
        }}

        .decision-question {{
            font-weight: 600;
            color: #856404;
            margin-bottom: 8px;
        }}

        .decision-logic {{
            color: #666;
            font-size: 0.95em;
            margin-bottom: 12px;
        }}

        .branches {{
            display: flex;
            gap: 10px;
            margin-top: 10px;
        }}

        .branch {{
            flex: 1;
            padding: 10px;
            background: white;
            border-radius: 5px;
            border: 2px solid #f39c12;
            text-align: center;
            font-weight: 500;
        }}

        .substeps {{
            margin-top: 20px;
            padding-left: 40px;
            border-left: 2px dashed #ccc;
            display: none;
        }}

        .substeps.expanded {{
            display: block;
        }}

        .expand-toggle {{
            display: inline-block;
            padding: 8px 15px;
            background: #667eea;
            color: white;
            border-radius: 5px;
            cursor: pointer;
            font-size: 0.9em;
            margin-top: 10px;
            transition: background 0.3s ease;
        }}

        .expand-toggle:hover {{
            background: #764ba2;
        }}

        .expand-toggle::before {{
            content: '▶ ';
        }}

        .expand-toggle.expanded::before {{
            content: '▼ ';
        }}

        .substep {{
            margin-bottom: 15px;
            padding: 15px;
            background: white;
            border-left: 3px solid #17a2b8;
            border-radius: 5px;
        }}

        .substep-title {{
            font-weight: 600;
            color: #17a2b8;
            margin-bottom: 8px;
        }}

        .notes {{
            background: #e8f5e9;
            padding: 10px 15px;
            border-left: 3px solid #4caf50;
            border-radius: 5px;
            margin-top: 10px;
            font-size: 0.9em;
            color: #2e7d32;
        }}

        .layer-badge {{
            display: inline-block;
            padding: 3px 10px;
            border-radius: 4px;
            font-size: 0.85em;
            font-weight: 500;
        }}

        .layer-core {{ background: #ffebee; color: #c62828; }}
        .layer-workflow {{ background: #e8f5e9; color: #2e7d32; }}
        .layer-memory {{ background: #e0f2f1; color: #00695c; }}
        .layer-tools {{ background: #fff3e0; color: #e65100; }}

        @media print {{
            body {{
                background: white;
            }}
            .step-card:hover {{
                transform: none;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🔄 ClarAIty - Execution Flow Visualization</h1>
            <p>Interactive visualization showing how code flows through components</p>
            <div class="stats">
                <div class="stat-card">
                    <div class="stat-number">{flow_data["stats"]["total_flows"]}</div>
                    <div class="stat-label">Execution Flows</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{flow_data["stats"]["total_steps"]}</div>
                    <div class="stat-label">Top-Level Steps</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{flow_data["stats"]["primary_flows"]}</div>
                    <div class="stat-label">Primary Flows</div>
                </div>
            </div>
        </div>

        <div id="flows-container"></div>
    </div>

    <script>
        // Embedded flow data
        const flowData = {json.dumps(flow_data, indent=8)};

        // Render flows
        function renderFlows() {{
            const container = document.getElementById('flows-container');

            flowData.flows.forEach(flow => {{
                const flowEl = createFlowElement(flow);
                container.appendChild(flowEl);
            }});
        }}

        function createFlowElement(flow) {{
            const div = document.createElement('div');
            div.className = 'flow-container';

            const complexityClass = `complexity-${{flow.complexity}}`;

            div.innerHTML = `
                <div class="flow-header">
                    <h2 class="flow-title">${{flow.is_primary ? '⭐ ' : ''}}${{flow.name}}</h2>
                    <div class="complexity-badge ${{complexityClass}}">${{flow.complexity.toUpperCase()}}</div>
                    <div class="flow-trigger">🎯 Trigger: ${{flow.trigger}}</div>
                    <div class="flow-description">${{flow.description}}</div>
                </div>
                <div class="timeline" id="timeline-${{flow.id}}"></div>
            `;

            const timeline = div.querySelector(`#timeline-${{flow.id}}`);
            flow.steps.forEach((step, index) => {{
                timeline.appendChild(createStepElement(step, index + 1, flow.id));
            }});

            return div;
        }}

        function createStepElement(step, number, flowId) {{
            const div = document.createElement('div');
            div.className = 'step';

            const markerClass = step.is_critical ? 'critical' : step.step_type === 'decision' ? 'decision' : '';
            const cardClass = step.is_critical ? 'critical' : step.step_type === 'decision' ? 'decision' : '';

            let metaHTML = '<div class="step-meta">';

            if (step.file_path) {{
                const lineRef = step.line_start ? `${{step.line_start}}${{step.line_end && step.line_end !== step.line_start ? '-' + step.line_end : ''}}` : '';
                metaHTML += `<div class="meta-item">📁 <span class="code-ref">${{step.file_path}}${{lineRef ? ':' + lineRef : ''}}</span></div>`;
            }}

            if (step.function_name) {{
                metaHTML += `<div class="meta-item">⚙️ <code>${{step.function_name}}</code></div>`;
            }}

            if (step.component_name) {{
                const layerClass = step.component_layer ? `layer-${{step.component_layer}}` : '';
                metaHTML += `<div class="meta-item"><span class="layer-badge ${{layerClass}}">${{step.component_name}}</span></div>`;
            }}

            metaHTML += '</div>';

            let decisionHTML = '';
            if (step.step_type === 'decision') {{
                decisionHTML = `
                    <div class="decision-box">
                        <div class="decision-question">❓ ${{step.decision_question || 'Decision Point'}}</div>
                        <div class="decision-logic">${{step.decision_logic || ''}}</div>
                        ${{step.branches ? `
                            <div class="branches">
                                ${{step.branches.map(branch => `
                                    <div class="branch">${{branch.label}}</div>
                                `).join('')}}
                            </div>
                        ` : ''}}
                    </div>
                `;
            }}

            let notesHTML = '';
            if (step.notes) {{
                notesHTML = `<div class="notes">💡 ${{step.notes}}</div>`;
            }}

            let substepsHTML = '';
            if (step.substeps && step.substeps.length > 0) {{
                const substepId = `substeps-${{step.id}}`;
                substepsHTML = `
                    <div class="expand-toggle" onclick="toggleSubsteps('${{substepId}}', this)">
                        Show ${{step.substeps.length}} substeps
                    </div>
                    <div class="substeps" id="${{substepId}}">
                        ${{step.substeps.map(substep => createSubstepHTML(substep)).join('')}}
                    </div>
                `;
            }}

            div.innerHTML = `
                <div class="step-marker ${{markerClass}}">
                    <span>${{number}}</span>
                </div>
                <div class="step-card ${{cardClass}}">
                    <div class="step-title">${{step.title}}</div>
                    <div class="step-description">${{step.description}}</div>
                    ${{metaHTML}}
                    ${{decisionHTML}}
                    ${{notesHTML}}
                    ${{substepsHTML}}
                </div>
            `;

            return div;
        }}

        function createSubstepHTML(substep) {{
            let metaItems = [];
            if (substep.file_path) {{
                const lineRef = substep.line_start ? `:${{substep.line_start}}` : '';
                metaItems.push(`📁 <span class="code-ref">${{substep.file_path}}${{lineRef}}</span>`);
            }}
            if (substep.component_name) {{
                const layerClass = substep.component_layer ? `layer-${{substep.component_layer}}` : '';
                metaItems.push(`<span class="layer-badge ${{layerClass}}">${{substep.component_name}}</span>`);
            }}

            let decisionHTML = '';
            if (substep.step_type === 'decision') {{
                decisionHTML = `
                    <div class="decision-box" style="margin-top: 10px; padding: 10px;">
                        <div class="decision-question" style="font-size: 0.9em;">❓ ${{substep.decision_question}}</div>
                        ${{substep.branches ? `
                            <div class="branches" style="font-size: 0.85em;">
                                ${{substep.branches.map(b => `<div class="branch">${{b.label}}</div>`).join('')}}
                            </div>
                        ` : ''}}
                    </div>
                `;
            }}

            // Handle deeper substeps recursively
            let deeperSubstepsHTML = '';
            if (substep.substeps && substep.substeps.length > 0) {{
                const deepSubstepId = `substeps-${{substep.id}}`;
                deeperSubstepsHTML = `
                    <div class="expand-toggle" style="font-size: 0.85em; padding: 5px 10px; margin-top: 8px;" onclick="toggleSubsteps('${{deepSubstepId}}', this)">
                        Show ${{substep.substeps.length}} sub-substeps
                    </div>
                    <div class="substeps" id="${{deepSubstepId}}" style="margin-top: 10px;">
                        ${{substep.substeps.map(ss => createSubstepHTML(ss)).join('')}}
                    </div>
                `;
            }}

            return `
                <div class="substep">
                    <div class="substep-title">${{substep.title}}</div>
                    <div style="color: #666; font-size: 0.9em; margin-bottom: 8px;">${{substep.description}}</div>
                    ${{metaItems.length > 0 ? `<div style="display: flex; gap: 10px; flex-wrap: wrap; font-size: 0.85em;">${{metaItems.join(' · ')}}</div>` : ''}}
                    ${{decisionHTML}}
                    ${{substep.notes ? `<div class="notes" style="font-size: 0.85em;">${{substep.notes}}</div>` : ''}}
                    ${{deeperSubstepsHTML}}
                </div>
            `;
        }}

        function toggleSubsteps(id, toggleEl) {{
            const substeps = document.getElementById(id);
            substeps.classList.toggle('expanded');
            toggleEl.classList.toggle('expanded');

            if (substeps.classList.contains('expanded')) {{
                toggleEl.textContent = toggleEl.textContent.replace('Show', 'Hide');
            }} else {{
                toggleEl.textContent = toggleEl.textContent.replace('Hide', 'Show');
            }}
        }}

        // Initialize
        renderFlows();
    </script>
</body>
</html>
'''

    # Write HTML file
    output_path = Path('flow-viz-embedded.html')
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"✅ Created {output_path}")
    print(f"📊 File size: {output_path.stat().st_size / 1024:.1f} KB")
    print(f"\n🚀 Open {output_path} in your browser to view the flow visualization!")

if __name__ == "__main__":
    create_flow_viz()
