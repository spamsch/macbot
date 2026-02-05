# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Son of Simon CLI.

This creates a standalone executable that can be used as a Tauri sidecar.

Usage:
    pyinstaller son.spec

Output:
    dist/son (macOS/Linux) or dist/son.exe (Windows)
"""

import sys
import os
from pathlib import Path

# Get the project root
project_root = Path(SPECPATH)

# Get codesign identity from environment variable (for CI) or use None for local dev
codesign_identity = os.environ.get('APPLE_SIGNING_IDENTITY', None)

# Dynamically find package locations (works in venv and system Python)
import litellm
import rich

litellm_path = Path(litellm.__file__).parent
rich_path = Path(rich.__file__).parent

# Build datas list dynamically
datas = [
    # Include macos-automation scripts
    ('macos-automation', 'macos-automation'),
    # Include built-in skills
    ('skills', 'skills'),
]

# Add litellm data files if they exist
litellm_data_paths = [
    ('litellm_core_utils/tokenizers', 'litellm/litellm_core_utils/tokenizers'),
    ('containers', 'litellm/containers'),
    ('llms/openai_like', 'litellm/llms/openai_like'),
    ('integrations', 'litellm/integrations'),
    ('proxy', 'litellm/proxy'),
]

for src_rel, dest in litellm_data_paths:
    src_path = litellm_path / src_rel
    if src_path.exists():
        datas.append((str(src_path), dest))

# Add litellm JSON files
for json_file in ['cost.json', 'model_prices_and_context_window_backup.json']:
    src_path = litellm_path / json_file
    if src_path.exists():
        datas.append((str(src_path), 'litellm'))

# Add rich unicode data if it exists
rich_unicode_path = rich_path / '_unicode_data'
if rich_unicode_path.exists():
    datas.append((str(rich_unicode_path), 'rich/_unicode_data'))

a = Analysis(
    ['src/macbot/cli.py'],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        # Ensure all macbot modules are included
        'macbot',
        'macbot.cli',
        'macbot.config',
        'macbot.service',
        'macbot.core',
        'macbot.core.agent',
        'macbot.core.scheduler',
        'macbot.core.task',
        'macbot.tasks',
        'macbot.tasks.registry',
        'macbot.tasks.macos_automation',
        'macbot.tasks.telegram',
        'macbot.tasks.paperless',
        'macbot.tasks.memory',
        'macbot.tasks.browser_automation',
        'macbot.tasks.web',
        'macbot.tasks.time_tracking',
        'macbot.tasks.file_read',
        'macbot.tasks.file_write',
        'macbot.cron',
        'macbot.cron.service',
        'macbot.cron.storage',
        'macbot.cron.executor',
        'macbot.telegram',
        'macbot.telegram.bot',
        'macbot.telegram.service',
        'macbot.memory',
        'macbot.memory.database',
        'macbot.memory.knowledge',
        'macbot.skills',
        'macbot.skills.models',
        'macbot.skills.loader',
        'macbot.skills.registry',
        'macbot.browser',
        'macbot.browser.safari',
        'macbot.providers',
        'macbot.providers.anthropic',
        'macbot.providers.openai',
        'macbot.providers.litellm_provider',
        'macbot.time_tracking',
        'macbot.utils',
        # External dependencies that might need explicit inclusion
        'httpx',
        'anthropic',
        'openai',
        'litellm',
        'litellm.litellm_core_utils',
        'litellm.litellm_core_utils.tokenizers',
        'litellm.litellm_core_utils.llm_cost_calc',
        'litellm.llms',
        'litellm.llms.anthropic',
        'litellm.llms.openai',
        'rich',
        'yaml',
        'pydantic',
        'dotenv',
        'croniter',
        'apscheduler',
        'telegram',
        'tiktoken',
        'tiktoken_ext',
        'tiktoken_ext.openai_public',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude unnecessary modules to reduce size
        'tkinter',
        'matplotlib',
        'PIL',
        'numpy',
        'pandas',
        'scipy',
        'cv2',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='son',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,  # Will build for current architecture
    codesign_identity=codesign_identity,
    entitlements_file=None,
)
