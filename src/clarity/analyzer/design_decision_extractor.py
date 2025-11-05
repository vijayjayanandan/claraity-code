"""
Design Decision Extractor - Parse design decisions from documentation

Extracts structured design decisions from markdown documentation files
like CODEBASE_CONTEXT.md which contains explicit "Design Decision" sections.
"""

import re
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass


@dataclass
class ExtractedDecision:
    """Represents an extracted design decision"""
    component_id: str
    decision_type: str
    question: str
    chosen_solution: str
    rationale: str
    alternatives_considered: List[str]
    trade_offs: str
    section_title: str


class DesignDecisionExtractor:
    """
    Extracts design decisions from markdown documentation

    Parses CODEBASE_CONTEXT.md and other documentation to extract
    structured design decision information.
    """

    # Pattern for design decision sections
    DECISION_PATTERN = re.compile(
        r'###\s+Decision\s+(\d+):\s+(.+?)\n'  # Title: "### Decision 1: Workflow vs Direct"
        r'\*\*Problem:\*\*\s+(.+?)\n'  # Problem statement
        r'\*\*Solution:\*\*\s+(.+?)(?:\n\n|\Z)',  # Solution (until double newline or end)
        re.DOTALL
    )

    # Alternative pattern for simpler format
    SIMPLE_DECISION_PATTERN = re.compile(
        r'##\s+(.+?)\n'  # Title
        r'(.+?)(?:\n##|\Z)',  # Content until next heading or end
        re.DOTALL
    )

    def __init__(self, docs_path: str = "CODEBASE_CONTEXT.md"):
        """
        Initialize DesignDecisionExtractor

        Args:
            docs_path: Path to documentation file
        """
        self.docs_path = Path(docs_path)
        self.decisions: List[ExtractedDecision] = []

    def extract(self) -> List[ExtractedDecision]:
        """
        Extract all design decisions from documentation

        Returns:
            List of ExtractedDecision objects
        """
        if not self.docs_path.exists():
            print(f"Warning: Documentation file not found: {self.docs_path}")
            return []

        with open(self.docs_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Find the "KEY DESIGN DECISIONS & RATIONALE" section
        decisions_section = self._extract_decisions_section(content)

        if decisions_section:
            self._parse_decisions_section(decisions_section)

        return self.decisions

    def _extract_decisions_section(self, content: str) -> Optional[str]:
        """
        Extract the design decisions section from document

        Args:
            content: Full document content

        Returns:
            Design decisions section text or None
        """
        # Look for the design decisions section
        pattern = r'##\s+🔄\s+KEY DESIGN DECISIONS & RATIONALE\s*\n(.*?)(?:\n##|\Z)'
        match = re.search(pattern, content, re.DOTALL)

        if match:
            return match.group(1)

        return None

    def _parse_decisions_section(self, section: str) -> None:
        """
        Parse individual decisions from the section

        Args:
            section: Design decisions section text
        """
        # Split into individual decision blocks
        decision_blocks = re.split(r'\n---\n|\n### Decision \d+:', section)

        decision_number = 0
        for block in decision_blocks:
            if not block.strip():
                continue

            decision_number += 1
            decision = self._parse_decision_block(block, decision_number)
            if decision:
                self.decisions.append(decision)

    def _parse_decision_block(self, block: str, number: int) -> Optional[ExtractedDecision]:
        """
        Parse a single decision block

        Args:
            block: Decision block text
            number: Decision number

        Returns:
            ExtractedDecision or None
        """
        lines = block.strip().split('\n')

        # Extract title (first line)
        title = lines[0].strip('# ').strip()

        # Initialize fields
        problem = ""
        solution = ""
        rationale = ""
        benefits = []
        tradeoff = ""
        alternatives = []
        files = []

        # Parse structured content
        current_field = None
        for line in lines[1:]:
            line = line.strip()

            if line.startswith('**Problem:**'):
                current_field = 'problem'
                problem = line.replace('**Problem:**', '').strip()
            elif line.startswith('**Solution:**'):
                current_field = 'solution'
                solution = line.replace('**Solution:**', '').strip()
            elif line.startswith('**Rationale:**'):
                current_field = 'rationale'
                rationale = line.replace('**Rationale:**', '').strip()
            elif line.startswith('**Benefits:**'):
                current_field = 'benefits'
            elif line.startswith('**Tradeoff:**') or line.startswith('**Tradeoffs:**'):
                current_field = 'tradeoff'
                tradeoff = line.replace('**Tradeoff:**', '').replace('**Tradeoffs:**', '').strip()
            elif line.startswith('**Result:**'):
                current_field = 'result'
            elif line.startswith('**Files:**'):
                current_field = 'files'
            elif line.startswith('- '):
                # List item
                item = line[2:].strip()
                if current_field == 'benefits':
                    benefits.append(item)
                elif current_field == 'files':
                    files.append(item)
            elif current_field == 'problem' and line:
                problem += ' ' + line
            elif current_field == 'solution' and line:
                solution += ' ' + line
            elif current_field == 'rationale' and line:
                rationale += ' ' + line
            elif current_field == 'tradeoff' and line:
                tradeoff += ' ' + line

        # Infer component_id from title or files
        component_id = self._infer_component_id(title, files)

        # Determine decision type
        decision_type = self._classify_decision_type(title)

        # Format as question
        question = problem if problem else f"How to handle {title.lower()}?"

        # Extract alternatives from solution text
        if "alternative" in solution.lower() or "considered" in solution.lower():
            # Try to extract alternatives
            alt_match = re.search(r'alternative[s]?:?\s*(.+?)\.', solution, re.IGNORECASE)
            if alt_match:
                alt_text = alt_match.group(1)
                alternatives = [a.strip() for a in alt_text.split(',')]

        return ExtractedDecision(
            component_id=component_id,
            decision_type=decision_type,
            question=question[:200] if question else "",
            chosen_solution=solution[:200] if solution else "",
            rationale=rationale[:200] if rationale else "",
            alternatives_considered=alternatives,
            trade_offs=tradeoff[:200] if tradeoff else "",
            section_title=title
        )

    def _infer_component_id(self, title: str, files: List[str]) -> str:
        """
        Infer component ID from decision title or related files

        Args:
            title: Decision title
            files: Related files

        Returns:
            Component ID
        """
        # Common mappings
        mappings = {
            'workflow': 'EXECUTIONENGINE',
            'direct': 'CODINGAGENT',
            'tool': 'EXECUTIONENGINE',
            'verification': 'VERIFICATIONLAYER',
            'iteration': 'EXECUTIONENGINE',
            'callback': 'EXECUTIONENGINE',
            'rag': 'HYBRIDRETRIEVER',
            'memory': 'MEMORYMANAGER',
            'llm': 'CODINGAGENT'
        }

        title_lower = title.lower()
        for keyword, component_id in mappings.items():
            if keyword in title_lower:
                return component_id

        # Try to extract from files
        if files:
            first_file = files[0].lower()
            if 'agent' in first_file:
                return 'CODINGAGENT'
            elif 'execution' in first_file:
                return 'EXECUTIONENGINE'
            elif 'verification' in first_file:
                return 'VERIFICATIONLAYER'
            elif 'retriever' in first_file:
                return 'HYBRIDRETRIEVER'

        # Default
        return 'CODINGAGENT'

    def _classify_decision_type(self, title: str) -> str:
        """
        Classify decision type from title

        Args:
            title: Decision title

        Returns:
            Decision type (architecture|implementation|technology|pattern)
        """
        title_lower = title.lower()

        if any(word in title_lower for word in ['architecture', 'system', 'component', 'layer']):
            return 'architecture'
        elif any(word in title_lower for word in ['tool', 'execution', 'direct', 'callback']):
            return 'implementation'
        elif any(word in title_lower for word in ['technology', 'framework', 'library', 'database']):
            return 'technology'
        elif any(word in title_lower for word in ['pattern', 'strategy', 'approach']):
            return 'pattern'
        else:
            return 'implementation'

    def get_summary(self) -> Dict[str, int]:
        """
        Get extraction summary

        Returns:
            Summary dict
        """
        return {
            'total_decisions': len(self.decisions),
            'by_type': self._count_by_type(),
            'by_component': self._count_by_component()
        }

    def _count_by_type(self) -> Dict[str, int]:
        """Count decisions by type"""
        counts = {}
        for decision in self.decisions:
            counts[decision.decision_type] = counts.get(decision.decision_type, 0) + 1
        return counts

    def _count_by_component(self) -> Dict[str, int]:
        """Count decisions by component"""
        counts = {}
        for decision in self.decisions:
            counts[decision.component_id] = counts.get(decision.component_id, 0) + 1
        return counts
