#!/usr/bin/env python
"""Direct validation runner that sets environment variables programmatically."""

import os
import sys

# Require the API key from environment
if not os.getenv('DASHSCOPE_API_KEY'):
    print("ERROR: Set DASHSCOPE_API_KEY environment variable first")
    sys.exit(1)

# Import and run the validation runner
from src.validation.runner import main

if __name__ == '__main__':
    # Override sys.argv to pass arguments
    sys.argv = [
        'run_validation_direct.py',
        '--scenario', 'easy_cli_weather',
        '--verbose',
        '--judge'
    ]
    main()
