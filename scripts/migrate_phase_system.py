"""
Phase System Migration for ClarAIty DB

Adds phase columns to components table and populates phase data
according to STATE_OF_THE_ART_AGENT_ARCHITECTURE.md.

This enables phase-driven development workflow:
- Phase 0: Foundation (5 components)
- Phase 1: Autonomous Execution (3 components)
- Phase 2: Intelligence & Recovery (3 components)
- Phase 3: Production Hardening (TBD)

Usage:
    python scripts/migrate_phase_system.py
"""

import sqlite3
from pathlib import Path


def migrate_phase_system(db_path: str = '.clarity/ai-coding-agent.db'):
    """Add phase columns and populate phase data."""

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print('[PHASE MIGRATION] Starting...')
    print('=' * 80)

    # Step 1: Add phase columns
    print('\n[1/5] Adding phase columns to components table...')
    try:
        cursor.execute('ALTER TABLE components ADD COLUMN phase TEXT')
        cursor.execute('ALTER TABLE components ADD COLUMN phase_order INTEGER')
        cursor.execute('ALTER TABLE components ADD COLUMN phase_sequence INTEGER DEFAULT 0')
        conn.commit()
        print('[OK] Columns added: phase, phase_order, phase_sequence')
    except sqlite3.OperationalError as e:
        if 'duplicate column name' in str(e).lower():
            print('[INFO] Columns already exist, skipping...')
        else:
            raise

    # Step 2: Populate Phase 0 (Foundation)
    print('\n[2/5] Populating Phase 0: Foundation...')
    phase_0_components = [
        'OBSERVABILITY_LAYER',
        'CLARITY_INTEGRATION',
        'WINDOWS_COMPATIBILITY',
        'LLM_FAILURE_HANDLER',
        'AGENT_INTERFACE'
    ]

    for idx, comp_id in enumerate(phase_0_components, 1):
        cursor.execute('''
            UPDATE components
            SET phase = 'Phase 0: Foundation',
                phase_order = 0,
                phase_sequence = ?
            WHERE id = ?
        ''', (idx, comp_id))

    conn.commit()
    print(f'[OK] Updated {len(phase_0_components)} components')

    # Step 3: Populate Phase 1 (Autonomous Execution)
    # Sequence based on STATE_OF_THE_ART_AGENT_ARCHITECTURE.md timeline
    print('\n[3/5] Populating Phase 1: Autonomous Execution...')
    phase_1_components = [
        ('SELF_TESTING_LAYER', 1),  # Week 1-2
        ('LONG_RUNNING_CONTROLLER', 2),  # Week 3-4, Days 1-2
        ('CHECKPOINT_MANAGER', 3),  # Week 3-4, Days 3-4
    ]

    for comp_id, seq in phase_1_components:
        cursor.execute('''
            UPDATE components
            SET phase = 'Phase 1: Autonomous Execution',
                phase_order = 1,
                phase_sequence = ?
            WHERE id = ?
        ''', (seq, comp_id))

    conn.commit()
    print(f'[OK] Updated {len(phase_1_components)} components')

    # Step 4: Populate Phase 2 (Intelligence & Recovery)
    # Sequence based on STATE_OF_THE_ART_AGENT_ARCHITECTURE.md timeline
    print('\n[4/5] Populating Phase 2: Intelligence & Recovery...')
    phase_2_components = [
        ('SMART_CONTEXT_LOADER', 1),  # Week 5-6, Days 1-2
        ('META_REASONING_ENGINE', 2),  # Week 5-6, Days 3-4
        ('ERROR_RECOVERY_SYSTEM', 3),  # Week 7-8, Days 1-2
    ]

    for comp_id, seq in phase_2_components:
        cursor.execute('''
            UPDATE components
            SET phase = 'Phase 2: Intelligence & Recovery',
                phase_order = 2,
                phase_sequence = ?
            WHERE id = ?
        ''', (seq, comp_id))

    conn.commit()
    print(f'[OK] Updated {len(phase_2_components)} components')

    # Step 5: Verify migration
    print('\n[5/5] Verification - Phase distribution:')
    result = cursor.execute('''
        SELECT phase, phase_order, COUNT(*) as count,
               SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) as completed
        FROM components
        WHERE phase IS NOT NULL
        GROUP BY phase, phase_order
        ORDER BY phase_order
    ''').fetchall()

    print('-' * 80)
    for phase, order, count, completed in result:
        pct = (completed / count * 100) if count > 0 else 0
        status = '[OK]' if completed == count else f'[{completed}/{count}]'
        print(f'{status:12} {phase:40} {pct:5.1f}%')

    print()
    print('=' * 80)
    print('[SUCCESS] Phase system migration complete!')
    print()
    print('[NEXT STEPS]')
    print('1. Test: python -c "from src.tools.clarity_tools import GetNextTaskTool; tool = GetNextTaskTool(); result = tool.execute(); print(result.output)"')
    print('2. Expected: SELF_TESTING_LAYER (Phase 1, sequence 1)')
    print('3. Then: Populate implementation specs for SELF_TESTING_LAYER')
    print('=' * 80)

    conn.close()


if __name__ == '__main__':
    migrate_phase_system()
