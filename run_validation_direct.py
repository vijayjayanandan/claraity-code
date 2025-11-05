#!/usr/bin/env python
"""Direct validation runner that sets environment variables programmatically."""

import os
import sys

# Set the API key
os.environ['DASHSCOPE_API_KEY'] = 'sk-4e4a13fc4efb48408e22eb9feb40a03d'

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
