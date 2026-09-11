from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import ROOT, Settings, load_credentials


def main():
    parser=argparse.ArgumentParser(description='Wonderland — 本地交互像素场景')
    sub=parser.add_subparsers(dest='command')
    sub.add_parser('studio',help='打开场景创作台（默认）')
    assets=sub.add_parser('assets',help='导入、扫描或检索素材')
    assets.add_argument('--scan',action='store_true');assets.add_argument('--import',dest='import_assets',action='store_true')
    assets.add_argument('--search');assets.add_argument('--raw',action='store_true')
    demo=sub.add_parser('demo',help='生成无需 API 的样板场景');demo.add_argument('--seed',type=int,default=42);demo.add_argument('--play',action='store_true')
    gen=sub.add_parser('generate',help='用 OpenAI 从描述生成场景')
    gen.add_argument('--prompt');gen.add_argument('--prompt-file',type=Path);gen.add_argument('--seed',type=int,default=42);gen.add_argument('--play',action='store_true')
    retry=sub.add_parser('retry',help='复用保存的计划与素材，重试指定生成任务')
    retry.add_argument('job_id');retry.add_argument('--play',action='store_true')
    play=sub.add_parser('play',help='离线打开已生成场景');play.add_argument('world',type=Path)
    render=sub.add_parser('render',help='无窗口渲染预览');render.add_argument('world',type=Path);render.add_argument('--scene',default='outdoor');render.add_argument('--out',type=Path,default=ROOT/'screenshots/preview.png')
    doctor=sub.add_parser('doctor',help='检查本地安装与密钥配置（不输出密钥）');doctor.add_argument('--api',action='store_true')
    args=parser.parse_args()
    try:
        if args.command in (None,'studio'):
            from .studio import Studio
            Studio().run()
        elif args.command=='doctor':
            from importlib.metadata import version
            print('Python',sys.version.split()[0])
            for package in ('pygame-ce','Pillow','openai','pydantic'):print(package,version(package))
            print('Assets:', 'present' if (ROOT/'assets/raw').is_dir() else 'missing')
            print('Credentials:', 'configured' if load_credentials() else 'missing')
            if args.api:
                settings=Settings.load();ids={m.id for m in settings.client().models.list().data}
                for model in (settings.llm_model,settings.image_model):print(model, 'available' if model in ids else 'not listed')
        elif args.command=='assets':
            from .catalog import Catalog,import_curated,scan_inventory
            cat=Catalog()
            try:
                if args.import_assets:import_curated(cat)
                if args.scan:scan_inventory(cat)
                if args.search:
                    for row in cat.search(args.search,raw=args.raw):
                        if args.raw:print(row[0],f'{row[1]}×{row[2]}','[未标注]')
                        else:
                            a=json.loads(row[3]);print(a['id'],a['name'],a['state'])
                if not args.search:print('已验证资源:',len(cat.all()))
            finally:cat.close()
        elif args.command=='demo':
            from .catalog import ensure_catalog
            from .world import compile_world,demo_spec,save_world
            cat=ensure_catalog()
            try:path=save_world(compile_world(demo_spec(),cat.all(),args.seed),ROOT)
            finally:cat.close()
            print(path)
            if args.play:
                from .runtime import Game
                from .world import load_world
                Game(load_world(path)).run()
        elif args.command in ('generate','retry'):
            from .agent import Generator
            if args.command=='generate':
                prompt=args.prompt_file.read_text(encoding='utf-8') if args.prompt_file else args.prompt
                if not prompt:parser.error('需要 --prompt 或 --prompt-file')
            generator=Generator(Settings.load())
            try:path=generator.resume(args.job_id) if args.command=='retry' else generator.generate(prompt,args.seed)
            finally:
                if generator.log:print('生成日志：',generator.log.path,file=sys.stderr)
            print(path)
            if args.play:
                from .runtime import Game
                from .world import load_world
                Game(load_world(path)).run()
        elif args.command in ('play','render'):
            from .runtime import Game
            from .world import load_world
            game=Game(load_world(args.world),headless=args.command=='render')
            if args.command=='play':game.run()
            else:game.set_scene(args.scene);game.screenshot(args.out);print(args.out)
    except KeyboardInterrupt:
        print('已停止。',file=sys.stderr);return 130
    except Exception as exc:
        from .agent import safe_error
        print('Wonderland:',safe_error(exc),file=sys.stderr);return 1
    return 0


if __name__=='__main__':raise SystemExit(main())
