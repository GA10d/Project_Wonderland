"""Build a local app entry point using the project's existing Python environment."""
from pathlib import Path
import plistlib
import shlex

root=Path(__file__).resolve().parent.parent
app=root/'build/Wonderland.app'
contents=app/'Contents'
(contents/'MacOS').mkdir(parents=True,exist_ok=True)
(contents/'Resources').mkdir(exist_ok=True)
with (contents/'Info.plist').open('wb') as stream:
    plistlib.dump(dict(CFBundleName='Wonderland',CFBundleDisplayName='Wonderland',
        CFBundleIdentifier='local.wonderland.scenes',CFBundleExecutable='Wonderland',
        CFBundlePackageType='APPL',CFBundleVersion='1',CFBundleShortVersionString='0.1',
        NSHighResolutionCapable=True,NSPrincipalClass='NSApplication'),stream)
launcher=contents/'MacOS/Wonderland'
launcher.write_text('#!/bin/sh\ncd '+shlex.quote(str(root))+' || exit 1\n'
                    'mkdir -p logs\n'
                    'export PYGAME_HIDE_SUPPORT_PROMPT=1\n'
                    'exec '+shlex.quote(str(root/'.venv/bin/python'))+' -u -m wonderland studio >> logs/desktop.log 2>&1\n')
launcher.chmod(0o755)
print(app)
