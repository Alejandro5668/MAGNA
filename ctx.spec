# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, \
    collect_dynamic_libs, copy_metadata

datas = []
datas += collect_data_files('pyfiglet')
datas += collect_data_files('textual')
datas += collect_data_files('chromadb')          # chromadb/migrations/**/*.sql — required
datas += collect_data_files('onnxruntime')
datas += copy_metadata('chromadb')               # chromadb reads its own dist version
datas += copy_metadata('onnxruntime')
datas += copy_metadata('tokenizers')
datas += collect_data_files('langchain')
datas += collect_data_files('langchain_core')
datas += collect_data_files('langgraph')
datas += copy_metadata('langchain')
datas += copy_metadata('langchain-core')
datas += copy_metadata('langchain-anthropic')
datas += copy_metadata('langgraph')
datas += copy_metadata('anthropic')

binaries = collect_dynamic_libs('onnxruntime')   # capi/*.dll + onnxruntime_pybind11_state.pyd

hiddenimports = collect_submodules('textual')
hiddenimports += [
    'textual.widgets._collapsible',
    'textual.widgets._option_list',
    'textual.widgets._rich_log',
]
hiddenimports += collect_submodules('chromadb')
hiddenimports += ['onnxruntime', 'tokenizers', 'posthog', 'pypika']
hiddenimports += collect_submodules('langchain')
hiddenimports += collect_submodules('langchain_core')
hiddenimports += collect_submodules('langchain_anthropic')
hiddenimports += collect_submodules('langgraph')
hiddenimports += ['langchain_anthropic.chat_models', 'langgraph.graph', 'langgraph.prebuilt']

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='MAGNA',
    icon='assets/icon.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=['onnxruntime*.dll', 'onnxruntime_pybind11_state.pyd', 'vcruntime140.dll'],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
