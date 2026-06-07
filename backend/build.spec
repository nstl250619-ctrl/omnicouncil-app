# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

block_cipher = None
backend_dir = Path(SPECPATH)

a = Analysis(
    [str(backend_dir / 'main.py')],
    pathex=[str(backend_dir)],
    binaries=[],
    datas=[
        (str(backend_dir / 'engine'), 'engine'),
        (str(backend_dir / 'api'), 'api'),
        (str(backend_dir / 'ws'), 'ws'),
        (str(backend_dir / 'shared'), 'shared'),
        (str(backend_dir / 'providers'), 'providers'),
        (str(backend_dir / 'browser'), 'browser'),
        (str(backend_dir / 'storage'), 'storage'),
        (str(backend_dir / 'config'), 'config'),
    ],
    hiddenimports=[
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'fastapi',
        'pydantic',
        'patchright',
        'api.events',
        'api.routes',
        'browser.factory',
        'browser.embedded_engine',
        'engine.layers.layer1_ai_access.manager',
        'engine.layers.layer2_scheduler.scheduler_center',
        'engine.layers.layer3_collector.result_collector',
        'engine.layers.layer4_comparison.comparison_engine',
        'shared.app_state',
        'shared.logger',
        'providers.base',
        'providers.deepseek',
        'providers.qianwen',
        'providers.gemini',
        'providers.chatgpt',
        'providers.mimo',
        'storage.local',
        'ws.connection',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'pandas', 'PIL', 'scipy'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='omnicouncil-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='omnicouncil-backend',
)
