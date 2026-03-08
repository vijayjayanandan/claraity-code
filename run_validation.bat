@echo off
if "%DASHSCOPE_API_KEY%"=="" echo ERROR: Set DASHSCOPE_API_KEY environment variable first && exit /b 1
python -m src.validation.run --scenario easy_cli_weather --verbose
