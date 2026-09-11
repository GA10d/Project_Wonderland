from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import threading
import time
from pathlib import Path

from PIL import Image
from pydantic import Field

from .catalog import Catalog, contact_sheet, digest, ensure_catalog
from .config import Settings, STYLE
from .diagnostics import EventLog, JobLock, atomic_json, exception_fields, safe_error
from .models import Asset, AssetNeed, SceneSpec, StrictModel
from .world import COMPILER_VERSION, compile_world, save_world


class Cancelled(RuntimeError): pass

NORMALIZER_VERSION='v2'
REVIEW_VERSION='v2'


class VisualReview(StrictModel):
    accepted: bool
    issues: list[str]
    explanation: str


class Generator:
    def __init__(self, settings: Settings, progress=print, cancelled: threading.Event | None=None):
        self.settings=settings;self.root=settings.root
        self.progress=progress;self.cancelled=cancelled or threading.Event()
        self.client=None
        self.job={};self.job_path=None
        self.log=None

    def event(self,event,**fields):
        if self.log:self.log.emit(event,**fields)

    def persist(self):
        if self.job_path:atomic_json(self.job_path,self.job)

    def check_cancel(self):
        if self.cancelled.is_set(): raise Cancelled("已取消；已通过验证的素材保留在素材库中。")

    def report(self,stage,detail):
        self.check_cancel();self.progress(detail)
        if self.job_path:
            self.job.update(stage=stage,detail=detail,updated_at=time.time())
            self.persist()
        self.event('stage',stage=stage,detail=detail)

    def record_usage(self,result,kind,model=None,duration=None):
        usage=getattr(result,'usage',None)
        call={'kind':kind,'model':getattr(result,'model',None) or model,
            'usage':usage.model_dump(mode='json') if usage else None,'time':time.time(),
            'request_id':getattr(result,'_request_id',None),'duration_seconds':duration}
        self.job.setdefault('calls',[]).append(call)
        self.persist();self.event('api_completed',**call)

    def api_call(self,kind,method,**kwargs):
        model=kwargs.get('model');started=time.monotonic()
        self.event('api_started',kind=kind,model=model)
        try:result=method(**kwargs)
        except Exception as exc:
            self.event('api_failed',kind=kind,model=model,duration_seconds=round(time.monotonic()-started,3),**exception_fields(exc))
            raise
        self.record_usage(result,kind,model,round(time.monotonic()-started,3))
        self.check_cancel()
        return result

    def generate(self,prompt: str,seed=42):
        if not prompt.strip():raise ValueError("请输入场景描述。")
        if len(prompt)>12000:raise ValueError("描述请控制在 12000 个字符以内。")
        manifest=self.root/'assets/manifests/limezu.json'
        revision=digest(manifest) if manifest.exists() else ''
        job_id=hashlib.sha256((prompt+str(seed)+self.settings.llm_model+self.settings.image_model+'planner-v4'+COMPILER_VERSION+revision).encode()).hexdigest()[:16]
        folder=self.root/'data/jobs';folder.mkdir(parents=True,exist_ok=True)
        self.job_path=folder/f'{job_id}.json'
        with JobLock(folder/f'{job_id}.lock'):
            return self._generate_locked(prompt,seed,job_id)

    def resume(self,job_id: str):
        """Retry a saved job after a fix, retaining its plan, assets and audit log."""
        if not re.fullmatch(r'[0-9a-f]{16}',job_id):raise ValueError('任务 ID 应为日志文件名中的 16 位小写十六进制字符。')
        folder=self.root/'data/jobs'
        self.job_path=folder/f'{job_id}.json'
        with JobLock(folder/f'{job_id}.lock'):
            job=json.loads(self.job_path.read_text())
            return self._generate_locked(job['prompt'],job['seed'],job_id)

    def _generate_locked(self,prompt,seed,job_id):
        self.log=EventLog(self.root,job_id)
        self.job=json.loads(self.job_path.read_text()) if self.job_path.exists() else {'prompt':prompt,'seed':seed,'calls':[]}
        self.job.update(job_id=job_id,log_path=str(self.log.path.relative_to(self.root)),run_id=self.log.run_id)
        previous_error=self.job.pop('error',None)
        self.job.pop('failed_stage',None)
        self.event('run_started',prompt=prompt,seed=seed,previous_error=previous_error,compiler_version=COMPILER_VERSION)
        if self.job.get('world_path') and (self.root/self.job['world_path']).exists():
            self.report('complete','读取已保存的生成结果。')
            self.event('run_completed',cached=True,world_path=self.job['world_path'])
            return self.root/self.job['world_path']
        cat=None
        try:
            self.report('catalog','检查素材目录与标注版本…')
            cat=ensure_catalog(self.root)
            self.event('catalog_loaded',validated_count=len(cat.all()),available_ids=[a['id'] for a in cat.brief()])
            self.client=self.settings.client()
            self.report('planning','理解描述，检索已验证素材…')
            if 'plan' in self.job:
                spec=SceneSpec.model_validate(self.job['plan'])
            else:
                spec=self.plan(prompt,cat)
                self.job['plan']=spec.model_dump(mode='json')
            self.persist();self.event('plan_ready',plan=spec.model_dump(mode='json'))
            if spec.unsupported_requests:
                self.progress('范围说明：'+'；'.join(spec.unsupported_requests))
            if len(spec.missing_assets)>self.settings.max_new_assets:
                raise ValueError(f"此描述需要 {len(spec.missing_assets)} 个新素材，超过每次 {self.settings.max_new_assets} 个的设置；请拆分描述或修改 config.toml。")
            bindings={}
            for need in spec.missing_assets:
                self.check_cancel()
                asset=self.resolve_asset(need,cat)
                bindings['generated.'+need.key]=asset.id
            resolved=spec.model_copy(deep=True)
            if resolved.ground_asset_id in bindings:resolved.ground_asset_id=bindings[resolved.ground_asset_id]
            for b in resolved.buildings:
                b.asset_id=bindings.get(b.asset_id,b.asset_id)
                for p in b.interior.furniture:p.asset_id=bindings.get(p.asset_id,p.asset_id)
            for p in resolved.outdoors:p.asset_id=bindings.get(p.asset_id,p.asset_id)
            resolved.missing_assets=[]
            self.report('compiling','铺设地形，布置房屋与内饰，验证门口和通路…')
            failures=[]
            for attempt in range(3):
                self.check_cancel()
                try:
                    world=compile_world(resolved,cat.all(),seed+attempt,prompt)
                    break
                except ValueError as exc:
                    failures.append(str(exc))
                    self.event('layout_rejected',attempt=attempt+1,seed=seed+attempt,error=str(exc),
                               **getattr(exc,'layout_details',{}))
            else:
                raise ValueError('布局检查未通过：'+failures[-1])
            self.report('saving','保存场景与素材快照…')
            path=save_world(world,self.root)
            self.job['world_path']=str(path.relative_to(self.root))
            self.job['compiler_version']=COMPILER_VERSION
            self.report('complete','场景已准备好，可以开始探索。')
            self.event('run_completed',cached=False,world_path=self.job['world_path'])
            return path
        except BaseException as exc:
            failed_stage=self.job.get('stage')
            self.job.update(stage='cancelled' if isinstance(exc,(Cancelled,KeyboardInterrupt)) else 'failed',
                            failed_stage=failed_stage,error=safe_error(exc),updated_at=time.time())
            self.persist();self.event('run_'+self.job['stage'],failed_stage=failed_stage,**exception_fields(exc))
            raise
        finally:
            if cat:cat.close()

    def plan(self,prompt,cat):
        system='''You design a playable local 2D pixel scene using a curated LimeZu asset catalog.
Return a SceneSpec, not code or tile grids. Respond with Chinese title/summary/names.
The world is a 64x48-cell outdoor area with 1-3 enterable buildings, each with an 18x16-cell interior.
The compiler ALREADY provides grass, an optional pond, automatically connected paths from every
house door to a main path, indoor wood floors, walls and doorways. Do NOT request or place path segments,
grass, water, wall, or floor objects for ordinary requests. A request for 小路 is satisfied by built-in paths.
Do not embellish it into a stone path, or invent any missing visual requirement the user did not ask for.
Use only catalog IDs below. Prefer reuse when an asset truly satisfies the request. All buildings have a door.
house.country is a large traditional two-story wood house with blue-gray roof; house.cabin is a small modern cabin.
Include all explicitly requested objects and visual attributes. Never claim an unsupported attribute is present.
Place 10-25 trees for meadows, 25-45 for forests; select oak/pine appropriately. Furnish homes with 5-9 objects.
Urban requests use biome=urban, a catalog gray ground tile if present, paved paths and only 4-10 street trees.
For an office interior set kind=office. It has a gray floor and a clear central aisle.
The office.* catalog contains AUTHOR-COMPOSED complete workstations with computers, keyboard/mouse,
desk and chair together; do not add extra chairs to those. Use 4 workstations total (west/east, max 2 per side)
plus 4-6 distinct support furnishings (printer, water dispenser, coffee, server, whiteboard, plant or cabinet).
"Many office supplies" is satisfied by these existing furnished desks and equipment. Do not invent a detailed
shopping list requiring every tiny stationery item in ONE sprite; compose existing readable objects instead.
Reuse a catalog modern office building (including generated assets) and gray ground if available.
Each furniture count is usually 1. Keep interiors traversable. Use small counts for large objects.
Simple input keywords may be expanded with coherent details. Longer explicit requests take precedence.
If genuinely missing, create AssetNeed with an English snake_case key and refer to it as generated.KEY.
Each missing item needs clear appearance, palette, viewing angle, and size in runtime cells.
The actual artwork has only 16 native pixels per cell, then a nearest-neighbor 2x display scale.
Budget details for that native canvas. Prioritize the object's silhouette and 2-3 recognizable components.
Put readable brand lettering on a sufficiently large storefront sign when requested; do not redundantly
require tiny logos, price labels, bag counts, or several miniature devices on a small furniture sprite.
Do not invent such mandatory micro-details from a request for a themed store.
New prop/furniture dimensions: 1-4 cells per edge. Building dimensions: 4-10 cells wide, 4-10 high.
Generated buildings use a fixed front-facing single centered ground-floor door and a rectangular footprint.
Terrain need must be size_cells=[1,1], solid=false; set ground_asset_id to generated.KEY for a custom ground texture.
ground_asset_id is otherwise null. It changes appearance only. Do not place terrain in outdoors/furniture lists.
Never generate existing beds/chairs/trees just because a synonym was used. At most 3 missing assets per scene.
Only movement, solid obstacles, and pressing E to enter/exit are supported. unsupported_requests lists requested
gameplay beyond this, or major unsupported geometry (bridges, elevations, infinite maps). It is empty otherwise.
Do not put normal missing visual props into unsupported_requests when they can be generated.
Available catalog:\n'''+json.dumps(cat.brief(),ensure_ascii=False)
        response=self.api_call('scene_plan',self.client.responses.parse,model=self.settings.llm_model,
            input=[{'role':'system','content':system},{'role':'user','content':prompt}],
            text_format=SceneSpec,reasoning={'effort':'high'},max_output_tokens=8000)
        if response.output_parsed is None:raise RuntimeError('模型没有返回有效场景计划，请修改描述后再试。')
        return response.output_parsed

    def resolve_asset(self,need:AssetNeed,cat:Catalog)->Asset:
        if any(v<1 or v>10 for v in need.size_cells):raise ValueError('生成素材尺寸需在 1 到 10 格之间。')
        if need.category=='terrain' and (need.size_cells!=[1,1] or need.solid):raise ValueError('地表材质必须是非实体的单格贴图。')
        # Preserve request IDs and accepted assets; processing versions have their
        # own output paths so failed originals can be repaired without resampling
        # an accepted world or paying for the same source image again.
        signature=hashlib.sha256((need.model_dump_json()+STYLE+'normalize-v1'+self.settings.image_model).encode()).hexdigest()[:16]
        aid='generated.'+signature
        existing=cat.all().get(aid)
        if existing:
            self.event('asset_reused',asset_id=aid,need=need.key)
            self.report('assets',f'复用已生成素材：{existing.name}');return existing
        self.report('assets',f'生成缺失素材：{need.description[:65]}')
        out=self.root/'assets/generated'/signature;out.mkdir(parents=True,exist_ok=True)
        references=self.root/'assets/previews/catalog.png'
        if not references.exists():contact_sheet(cat,references)
        notes=''
        for attempt in range(self.settings.max_image_attempts):
            self.check_cancel()
            self.event('asset_attempt',need=need.key,asset_id=aid,attempt=attempt+1)
            original=out/f'original_{attempt}.png'
            if not original.exists():
                instruction=f'''Create ONE production pixel-art game asset, not a scene or a mockup.
Required object: {need.description}
Match the attached catalog's low-resolution 16px-per-tile pixel clusters, perspective, subdued palette,
top-left lighting and precise 1-native-pixel outlines. No captions, watermarks, annotations or multiple views.
If the required object explicitly includes a sign or lettering, include that lettering on the object.
No blur, no anti-aliasing. Keep colored indicators and component borders distinct at the final native size.
The final native canvas is {need.size_cells[0]*16}x{need.size_cells[1]*16} pixels before 2x nearest-neighbor enlargement.
Compose large readable pixel clusters that survive conversion to this resolution.
'''
                if need.category=='terrain':
                    instruction+='Fill the entire canvas with a top-down seamless repeating terrain material. No objects, horizon, borders or shadow. Opaque background.'
                else:
                    instruction+='Transparent background; exactly one isolated complete object, centered with a small clear margin. Ground contact at bottom center. No floor patch or cast shadow outside the object.'
                    if need.category=='building':instruction+=' A single centered front door MUST meet the bottom ground plane. One floor, roof above, no stairs, no side entrances.'
                instruction+='\nPrevious review corrections: '+notes
                with references.open('rb') as reference:
                    result=self.api_call('asset_image',self.client.images.edit,model=self.settings.image_model,image=[reference],prompt=instruction,
                        size='1024x1024',quality=self.settings.image_quality,
                        background='opaque' if need.category=='terrain' else 'transparent',output_format='png',n=1)
                if not result.data or not result.data[0].b64_json:raise RuntimeError('图像 API 未返回图片数据。')
                original.write_bytes(base64.b64decode(result.data[0].b64_json))
                self.report('assets','原图已保存，正在适配项目像素规格…')
            else:
                self.event('image_cached',asset_id=aid,attempt=attempt+1,path=str(original.relative_to(self.root)))
            target=out/f'normalized_{NORMALIZER_VERSION}_{attempt}.png'
            try:normalize_generated(original,target,need)
            except ValueError as exc:
                self.event('normalization_rejected',asset_id=aid,attempt=attempt+1,error=str(exc))
                notes=str(exc);continue
            self.report('review','检查素材的透明背景、像素密度、轮廓与场景用途…')
            # Review the FINAL pixel asset against the catalog, not just the high-res original.
            preview=out/f'review_{NORMALIZER_VERSION}_{attempt}.png'
            with Image.open(target) as im:
                if need.category=='terrain':
                    tiled=Image.new('RGBA',(im.width*4,im.height*4))
                    for ty in range(4):
                        for tx in range(4):tiled.paste(im,(tx*im.width,ty*im.height))
                    tiled.resize((512,512),Image.Resampling.NEAREST).save(preview)
                else:im.resize((im.width*4,im.height*4),Image.Resampling.NEAREST).save(preview)
            instruction=f'''Judge this FINAL pixel game asset against the reference catalog.
User's scene request: {self.job.get('prompt','')}
Planned asset design: {need.description}
Its native artwork canvas is {need.size_cells[0]*16}x{need.size_cells[1]*16} pixels, displayed at 2x;
the review image is further enlarged with nearest-neighbor only. Judge readability at that native budget.
Reject a missing/wrong object, wrong view, illegible main silhouette, incoherent palette, non-pixel/photo
style, missing recognizable functional components, or absent centered ground-level front door for a building.
Preserve explicit user requirements, including the identity of a requested branded storefront.
For small props, decorative micro-details added by the planner (tiny text, exact bag counts, price tags)
may be simplified when the user did not explicitly require those details on that specific prop.
List minor imperfections as suggestions; do not turn them into blockers for an otherwise readable asset.
First image is candidate, second is reference. Return concise Chinese issues and explanation.'''
            fingerprint=hashlib.sha256((digest(target)+digest(references)+instruction+
                self.settings.llm_model+REVIEW_VERSION).encode()).hexdigest()
            review_path=out/f'review_{NORMALIZER_VERSION}_{REVIEW_VERSION}_{attempt}.json'
            cached=json.loads(review_path.read_text()) if review_path.exists() else {}
            verdict=None
            if cached.get('fingerprint')==fingerprint and cached.get('result'):
                verdict=VisualReview.model_validate(cached['result'])
                self.event('review_cached',asset_id=aid,attempt=attempt+1,accepted=verdict.accepted)
            else:
                review=self.api_call('asset_review',self.client.responses.parse,model=self.settings.llm_model,
                    input=[{'role':'user','content':[
                        {'type':'input_text','text':instruction},
                        {'type':'input_image','image_url':data_url(preview)},
                        {'type':'input_image','image_url':data_url(references)},
                    ]}],text_format=VisualReview,max_output_tokens=2000)
                verdict=review.output_parsed
                atomic_json(review_path,dict(fingerprint=fingerprint,result=verdict.model_dump(mode='json') if verdict else None))
            self.event('asset_reviewed',asset_id=aid,need=need.key,attempt=attempt+1,
                       normalizer=NORMALIZER_VERSION,result=verdict.model_dump(mode='json') if verdict else None)
            if not verdict or not verdict.accepted:
                notes='; '.join(verdict.issues) if verdict else 'No valid review.';continue
            w,h=need.size_cells[0]*32,need.size_cells[1]*32
            anchor=(w//2,h-4)
            if need.category=='terrain':anchor=(0,0)
            if need.category=='building':collision=(-int(w*.38),-int(h*.22),int(w*.76),int(h*.22))
            elif need.solid:collision=(-max(8,w//4),-max(6,h//8),max(16,w//2),max(12,h//8))
            else:collision=None
            asset=Asset(id=aid,name=need.description[:80],category='tile' if need.category=='terrain' else need.category,
                tags=[need.key,need.description],source=str(original.relative_to(self.root)),image=str(target.relative_to(self.root)),
                size=(w,h),anchor=anchor,collision=collision,door=(0,8) if need.category=='building' else None,
                sha256=digest(target),provenance={'kind':'openai_generated','request':need.model_dump(mode='json'),
                    'model':self.settings.image_model,'quality':self.settings.image_quality,'reference':'LimeZu local catalog',
                    'normalizer':NORMALIZER_VERSION,'review':verdict.model_dump(mode='json')})
            (out/'asset.json').write_text(asset.model_dump_json(indent=2))
            cat.register(asset);self.report('assets','新素材通过验证并已入库。');return asset
        raise RuntimeError(f'素材 {need.key} 在 {self.settings.max_image_attempts} 次尝试后仍未通过验证：{notes}')


def data_url(path):return 'data:image/png;base64,'+base64.b64encode(path.read_bytes()).decode()


def normalize_generated(source:Path,target:Path,need:AssetNeed):
    """Deterministic art processing only; gameplay collision uses explicit templates."""
    im=Image.open(source).convert('RGBA')
    native=(need.size_cells[0]*16,need.size_cells[1]*16)
    if need.category=='terrain':
        im=im.convert('RGB').resize(native,Image.Resampling.BOX)
        # Lock opposing edge texels. Inspect a repeated preview in visual review.
        for y in range(im.height):
            c=tuple((a+b)//2 for a,b in zip(im.getpixel((0,y)),im.getpixel((im.width-1,y))))
            im.putpixel((0,y),c);im.putpixel((im.width-1,y),c)
        for x in range(im.width):
            c=tuple((a+b)//2 for a,b in zip(im.getpixel((x,0)),im.getpixel((x,im.height-1))))
            im.putpixel((x,0),c);im.putpixel((x,im.height-1),c)
        im=im.quantize(colors=48,dither=Image.Dither.NONE).convert('RGBA')
    else:
        alpha=im.getchannel('A')
        extrema=alpha.getextrema()
        if extrema[0]>8:raise ValueError('需要真实透明背景，不能把不透明背景视作完成。')
        mask=alpha.point(lambda value:255 if value>=100 else 0)
        box=mask.getbbox()
        if not box:raise ValueError('生成素材为空。')
        im=im.crop(box)
        im.thumbnail((native[0]-2,native[1]-2),Image.Resampling.BOX)
        im.putalpha(im.getchannel('A').point(lambda value:255 if value>=128 else 0))
        alpha=im.getchannel('A')
        # Median-cut can erase a tiny but distinct indicator (e.g. two green
        # display pixels) in favour of many nearly identical cabinet shades.
        # Maximum coverage preserves distinct accent colors at the same budget.
        rgb=im.convert('RGB').quantize(colors=64,method=Image.Quantize.MAXCOVERAGE,
                                      dither=Image.Dither.NONE).convert('RGBA');rgb.putalpha(alpha)
        canvas=Image.new('RGBA',native)
        canvas.alpha_composite(rgb,((native[0]-rgb.width)//2,native[1]-rgb.height-1));im=canvas
        if not im.getbbox():raise ValueError('缩小后没有可见像素。')
    im=im.resize((native[0]*2,native[1]*2),Image.Resampling.NEAREST)
    if any(v%32 for v in im.size):raise ValueError('生成素材没有对齐 32 像素格子。')
    im.save(target)
