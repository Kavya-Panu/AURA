AURA Fast Response — Qwen3 8B
================================

This package keeps qwen3:8b but changes the slow settings:

- Disables Qwen3 thinking mode for ordinary robot questions.
- Limits answers to approximately 220 generated tokens.
- Uses a 2048-token Ollama context to reduce VRAM use.
- Keeps the model loaded continuously after startup.
- Warms the model before the You: prompt appears.
- Keeps only four conversation turns.
- Shows the generation time after every answer.

Install/update:
    python -m pip install -r requirements_brain.txt --upgrade

Start:
    python run_aura_brain.py

While AURA is open, use another PowerShell window:
    ollama ps

Check PROCESSOR:
- 100% GPU: best result for qwen3:8b.
- Mixed CPU/GPU: qwen3:8b does not fully fit in VRAM and will remain slower.
- 100% CPU: GPU acceleration is not active.

The first startup now takes longer because AURA warms the model. Questions should
then respond substantially faster.
