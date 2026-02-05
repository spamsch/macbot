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
from pathlib import Path

# Get the project root
project_root = Path(SPECPATH)

a = Analysis(
    ['src/macbot/cli.py'],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        # Include macos-automation scripts
        ('macos-automation', 'macos-automation'),
    ],
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
        'rich',
        'yaml',
        'pydantic',
        'dotenv',
        'croniter',
        'apscheduler',
        'telegram',
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
    codesign_identity=None,
    entitlements_file=None,
)
