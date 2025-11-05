"""
Blueprint Approval UI and Server

Simple HTTP server that displays blueprint and waits for user approval.
"""

import json
import logging
import threading
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional, Tuple
from pathlib import Path

from ..core.blueprint import Blueprint

logger = logging.getLogger(__name__)


class ApprovalDecision:
    """User's decision on the blueprint."""

    def __init__(self, approved: bool, feedback: Optional[str] = None):
        self.approved = approved
        self.feedback = feedback


class ApprovalServer:
    """
    HTTP server for blueprint approval.

    Serves HTML visualization and waits for user decision.
    """

    def __init__(self, blueprint: Blueprint, port: int = 8765):
        """
        Initialize approval server.

        Args:
            blueprint: Blueprint to display
            port: Port to serve on (default: 8765)
        """
        self.blueprint = blueprint
        self.port = port
        self.decision: Optional[ApprovalDecision] = None
        self.server: Optional[HTTPServer] = None
        self.server_thread: Optional[threading.Thread] = None

    def start_and_wait(self, auto_open: bool = True) -> ApprovalDecision:
        """
        Start server and wait for user decision.

        Args:
            auto_open: Automatically open browser (default: True)

        Returns:
            ApprovalDecision with user's choice
        """
        logger.info(f"Starting approval server on port {self.port}")

        # Create request handler with reference to this instance
        server_instance = self

        class ApprovalRequestHandler(BaseHTTPRequestHandler):
            """Handle HTTP requests for approval UI."""

            def log_message(self, format, *args):
                """Suppress default logging."""
                pass

            def do_GET(self):
                """Serve the approval UI or handle decision."""
                if self.path == "/":
                    # Serve main approval page
                    html = generate_approval_html(server_instance.blueprint)
                    self.send_response(200)
                    self.send_header("Content-type", "text/html")
                    self.end_headers()
                    self.wfile.write(html.encode())

                elif self.path.startswith("/api/decision"):
                    # Handle decision (approve/reject)
                    if "?action=approve" in self.path:
                        server_instance.decision = ApprovalDecision(approved=True)
                        logger.info("User approved the blueprint")
                    elif "?action=reject" in self.path:
                        server_instance.decision = ApprovalDecision(approved=False)
                        logger.info("User rejected the blueprint")

                    # Send success response
                    self.send_response(200)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "ok"}).encode())

                else:
                    # 404
                    self.send_response(404)
                    self.end_headers()

        # Start server in background thread
        self.server = HTTPServer(("localhost", self.port), ApprovalRequestHandler)
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()

        # Open browser
        url = f"http://localhost:{self.port}"
        if auto_open:
            logger.info(f"Opening browser at {url}")
            webbrowser.open(url)
        else:
            logger.info(f"Approval UI available at {url}")

        # Wait for decision
        logger.info("Waiting for user decision...")
        while self.decision is None:
            threading.Event().wait(0.1)

        # Shutdown server
        logger.info("Decision received, shutting down server")
        self.server.shutdown()

        return self.decision


def generate_approval_html(blueprint: Blueprint) -> str:
    """
    Generate HTML for blueprint approval UI.

    Args:
        blueprint: Blueprint to visualize

    Returns:
        Complete HTML string
    """
    blueprint_json = json.dumps(blueprint.to_dict(), indent=2)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ClarAIty - Architecture Blueprint Approval</title>
    <style>
        {get_approval_styles()}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🏗️ Architecture Blueprint</h1>
            <p class="subtitle">Review the plan before code generation begins</p>
        </div>

        <div class="blueprint-overview">
            <h2>{blueprint.task_description}</h2>
            <div class="stats">
                <div class="stat-card">
                    <div class="stat-value">{len(blueprint.components)}</div>
                    <div class="stat-label">Components</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{len(blueprint.file_actions)}</div>
                    <div class="stat-label">File Changes</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{blueprint.estimated_complexity or 'N/A'}</div>
                    <div class="stat-label">Complexity</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{blueprint.estimated_time or 'N/A'}</div>
                    <div class="stat-label">Est. Time</div>
                </div>
            </div>
        </div>

        <div class="section">
            <h3>🎯 Components to Build</h3>
            <div class="component-list">
                {generate_component_cards(blueprint)}
            </div>
        </div>

        <div class="section">
            <h3>💡 Design Decisions</h3>
            <div class="decision-list">
                {generate_decision_cards(blueprint)}
            </div>
        </div>

        <div class="section">
            <h3>📁 File Changes</h3>
            <div class="file-action-list">
                {generate_file_action_cards(blueprint)}
            </div>
        </div>

        {generate_prerequisites_section(blueprint)}
        {generate_risks_section(blueprint)}

        <div class="action-bar">
            <button class="btn btn-reject" onclick="rejectBlueprint()">
                ❌ Reject - Needs Changes
            </button>
            <button class="btn btn-approve" onclick="approveBlueprint()">
                ✅ Approve - Start Building
            </button>
        </div>

        <div id="decision-message" class="decision-message"></div>
    </div>

    <script>
        {get_approval_javascript()}
    </script>
</body>
</html>"""

    return html


def generate_component_cards(blueprint: Blueprint) -> str:
    """Generate HTML for component cards."""
    if not blueprint.components:
        return '<p class="empty-message">No components defined</p>'

    html_parts = []
    for comp in blueprint.components:
        responsibilities = "".join([f"<li>{r}</li>" for r in comp.responsibilities])
        methods = ", ".join(comp.key_methods) if comp.key_methods else "N/A"

        html_parts.append(f"""
        <div class="component-card">
            <div class="card-header">
                <span class="component-type">{comp.type.value}</span>
                <h4>{comp.name}</h4>
            </div>
            <p class="component-purpose">{comp.purpose}</p>
            <div class="component-details">
                <strong>Responsibilities:</strong>
                <ul>{responsibilities}</ul>
                <strong>File:</strong> <code>{comp.file_path}</code><br>
                <strong>Key Methods:</strong> <code>{methods}</code>
            </div>
        </div>
        """)

    return "\n".join(html_parts)


def generate_decision_cards(blueprint: Blueprint) -> str:
    """Generate HTML for design decision cards."""
    if not blueprint.design_decisions:
        return '<p class="empty-message">No design decisions specified</p>'

    html_parts = []
    for dd in blueprint.design_decisions:
        alternatives = ""
        if dd.alternatives_considered:
            alt_items = "".join([f"<li>{alt}</li>" for alt in dd.alternatives_considered])
            alternatives = f"<strong>Alternatives considered:</strong><ul>{alt_items}</ul>"

        trade_offs = ""
        if dd.trade_offs:
            trade_offs = f"<strong>Trade-offs:</strong><p>{dd.trade_offs}</p>"

        html_parts.append(f"""
        <div class="decision-card">
            <div class="decision-header">
                <span class="decision-category">{dd.category or 'general'}</span>
                <h4>{dd.decision}</h4>
            </div>
            <p class="decision-rationale"><strong>Why:</strong> {dd.rationale}</p>
            {alternatives}
            {trade_offs}
        </div>
        """)

    return "\n".join(html_parts)


def generate_file_action_cards(blueprint: Blueprint) -> str:
    """Generate HTML for file action cards."""
    if not blueprint.file_actions:
        return '<p class="empty-message">No file changes specified</p>'

    html_parts = []
    for fa in blueprint.file_actions:
        action_class = {
            "create": "action-create",
            "modify": "action-modify",
            "delete": "action-delete",
        }.get(fa.action.value, "")

        action_icon = {
            "create": "➕",
            "modify": "✏️",
            "delete": "❌",
        }.get(fa.action.value, "📝")

        lines_info = f"~{fa.estimated_lines} lines" if fa.estimated_lines else "Unknown size"

        html_parts.append(f"""
        <div class="file-action-card {action_class}">
            <div class="file-action-header">
                <span class="file-action-icon">{action_icon}</span>
                <span class="file-action-type">{fa.action.value.upper()}</span>
                <code class="file-path">{fa.file_path}</code>
            </div>
            <p class="file-action-description">{fa.description}</p>
            <div class="file-action-meta">{lines_info}</div>
        </div>
        """)

    return "\n".join(html_parts)


def generate_prerequisites_section(blueprint: Blueprint) -> str:
    """Generate prerequisites section."""
    if not blueprint.prerequisites:
        return ""

    items = "".join([f"<li>{p}</li>" for p in blueprint.prerequisites])

    return f"""
    <div class="section warning-section">
        <h3>⚠️ Prerequisites</h3>
        <ul>{items}</ul>
    </div>
    """


def generate_risks_section(blueprint: Blueprint) -> str:
    """Generate risks section."""
    if not blueprint.risks:
        return ""

    items = "".join([f"<li>{r}</li>" for r in blueprint.risks])

    return f"""
    <div class="section danger-section">
        <h3>🚨 Potential Risks</h3>
        <ul>{items}</ul>
    </div>
    """


def get_approval_styles() -> str:
    """Get CSS styles for approval UI."""
    return """
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: #333;
            padding: 20px;
        }

        .container {
            max-width: 1200px;
            margin: 0 auto;
        }

        .header {
            background: white;
            border-radius: 10px;
            padding: 30px;
            margin-bottom: 20px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.15);
            text-align: center;
        }

        .header h1 {
            color: #667eea;
            font-size: 2.5em;
            margin-bottom: 10px;
        }

        .subtitle {
            color: #666;
            font-size: 1.1em;
        }

        .blueprint-overview {
            background: white;
            border-radius: 10px;
            padding: 30px;
            margin-bottom: 20px;
            box-shadow: 0 5px 20px rgba(0,0,0,0.1);
        }

        .blueprint-overview h2 {
            color: #333;
            margin-bottom: 20px;
        }

        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
        }

        .stat-card {
            background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
            border-radius: 8px;
            padding: 20px;
            text-align: center;
        }

        .stat-value {
            font-size: 2em;
            font-weight: bold;
            color: #667eea;
            margin-bottom: 5px;
        }

        .stat-label {
            font-size: 0.9em;
            color: #666;
        }

        .section {
            background: white;
            border-radius: 10px;
            padding: 30px;
            margin-bottom: 20px;
            box-shadow: 0 5px 20px rgba(0,0,0,0.1);
        }

        .section h3 {
            color: #333;
            margin-bottom: 20px;
            font-size: 1.5em;
        }

        .component-list, .decision-list, .file-action-list {
            display: grid;
            gap: 15px;
        }

        .component-card, .decision-card, .file-action-card {
            background: #f8f9fa;
            border-left: 5px solid #667eea;
            border-radius: 8px;
            padding: 20px;
            transition: all 0.3s ease;
        }

        .component-card:hover, .decision-card:hover, .file-action-card:hover {
            transform: translateX(5px);
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
        }

        .card-header {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 10px;
        }

        .component-type, .decision-category {
            background: #667eea;
            color: white;
            padding: 4px 12px;
            border-radius: 15px;
            font-size: 0.85em;
            font-weight: 500;
        }

        .component-card h4, .decision-card h4 {
            color: #333;
            font-size: 1.2em;
        }

        .component-purpose, .decision-rationale {
            color: #666;
            line-height: 1.6;
            margin-bottom: 15px;
        }

        .component-details strong {
            color: #333;
            display: inline-block;
            margin-top: 10px;
        }

        .component-details ul {
            margin-left: 20px;
            margin-top: 5px;
            margin-bottom: 10px;
        }

        .component-details code, code {
            background: #e9ecef;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: 'Courier New', monospace;
            font-size: 0.9em;
        }

        .file-action-header {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 10px;
        }

        .file-action-icon {
            font-size: 1.5em;
        }

        .file-action-type {
            background: #6c757d;
            color: white;
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 0.8em;
            font-weight: 600;
        }

        .action-create { border-left-color: #28a745; }
        .action-create .file-action-type { background: #28a745; }

        .action-modify { border-left-color: #ffc107; }
        .action-modify .file-action-type { background: #ffc107; color: #333; }

        .action-delete { border-left-color: #dc3545; }
        .action-delete .file-action-type { background: #dc3545; }

        .file-path {
            color: #667eea;
            font-weight: 500;
        }

        .file-action-description {
            color: #666;
            line-height: 1.6;
            margin-bottom: 10px;
        }

        .file-action-meta {
            color: #999;
            font-size: 0.85em;
        }

        .warning-section {
            background: #fff3cd;
            border-left: 5px solid #ffc107;
        }

        .danger-section {
            background: #f8d7da;
            border-left: 5px solid #dc3545;
        }

        .warning-section ul, .danger-section ul {
            margin-left: 20px;
            margin-top: 10px;
        }

        .warning-section li, .danger-section li {
            margin-bottom: 8px;
            line-height: 1.5;
        }

        .action-bar {
            position: sticky;
            bottom: 20px;
            background: white;
            border-radius: 10px;
            padding: 20px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            display: flex;
            gap: 20px;
            justify-content: center;
            margin-top: 30px;
        }

        .btn {
            padding: 15px 40px;
            font-size: 1.1em;
            font-weight: 600;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.3s ease;
        }

        .btn-approve {
            background: linear-gradient(135deg, #28a745 0%, #20c997 100%);
            color: white;
        }

        .btn-approve:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 20px rgba(40, 167, 69, 0.4);
        }

        .btn-reject {
            background: #f8f9fa;
            color: #dc3545;
            border: 2px solid #dc3545;
        }

        .btn-reject:hover {
            background: #dc3545;
            color: white;
        }

        .decision-message {
            position: fixed;
            top: 20px;
            right: 20px;
            background: white;
            padding: 20px 30px;
            border-radius: 8px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            font-size: 1.1em;
            font-weight: 600;
            display: none;
            z-index: 1000;
        }

        .decision-message.show {
            display: block;
            animation: slideIn 0.3s ease-out;
        }

        @keyframes slideIn {
            from {
                opacity: 0;
                transform: translateX(100px);
            }
            to {
                opacity: 1;
                transform: translateX(0);
            }
        }

        .empty-message {
            color: #999;
            font-style: italic;
            text-align: center;
            padding: 20px;
        }
    """


def get_approval_javascript() -> str:
    """Get JavaScript for approval UI interactions."""
    return """
        function approveBlueprint() {
            fetch('/api/decision?action=approve')
                .then(() => {
                    showMessage('✅ Blueprint Approved! Code generation will begin...', '#28a745');
                    setTimeout(() => {
                        window.close();
                    }, 2000);
                });
        }

        function rejectBlueprint() {
            fetch('/api/decision?action=reject')
                .then(() => {
                    showMessage('❌ Blueprint Rejected. Returning to agent...', '#dc3545');
                    setTimeout(() => {
                        window.close();
                    }, 2000);
                });
        }

        function showMessage(text, color) {
            const msg = document.getElementById('decision-message');
            msg.textContent = text;
            msg.style.background = color;
            msg.style.color = 'white';
            msg.classList.add('show');
        }
    """
