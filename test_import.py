import os
import traceback

os.environ['DASHSCOPE_API_KEY'] = 'sk-4e4a13fc4efb48408e22eb9feb40a03d'

try:
    from src.validation import runner
    print("SUCCESS: Import worked!")
except Exception as e:
    print(f"ERROR: {e}")
    traceback.print_exc()
