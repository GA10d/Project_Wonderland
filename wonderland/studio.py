from __future__ import annotations

import queue
import json
import os
import random
import threading
import time
from datetime import datetime
from pathlib import Path

import pygame

from .agent import Cancelled, Generator, safe_error
from .catalog import ensure_catalog
from .config import ROOT, Settings
from .diagnostics import EventLog, exception_fields, redact
from .runtime import CREAM, INK, MUTED, Game, font
from .world import compile_world, demo_spec, load_world, save_world

EXAMPLES=[
    ("草原小屋","一片安静的草原，中央有一间乡间木屋，门前有小路和水井，四周有橡树和松树，右侧有池塘。屋内有床、木桌、椅子、柜子、盆栽和壁炉。"),
    ("林间营地","松林中有一间小型营地小屋，门前立着木牌，旁边有石头和水井。屋内有床、桌椅和落地灯。"),
    ("都市办公室","我要一个都市场景，有一个可以进入的 office，里面有非常多办公用品。"),
]

UI_SIZE=(1280,900)


def ui_viewport(display_size):
    scale=min(display_size[0]/UI_SIZE[0],display_size[1]/UI_SIZE[1])
    size=(round(UI_SIZE[0]*scale),round(UI_SIZE[1]*scale))
    return pygame.Rect((display_size[0]-size[0])//2,(display_size[1]-size[1])//2,*size)


def ui_position(position,display_size,window_size):
    """Map window points through the actual letterboxed UI, including Retina DPI."""
    x=position[0]*display_size[0]/window_size[0]
    y=position[1]*display_size[1]/window_size[1]
    view=ui_viewport(display_size)
    return ((x-view.x)*UI_SIZE[0]/view.width,(y-view.y)*UI_SIZE[1]/view.height)


class Studio:
    def __init__(self,root=ROOT):
        self.root=root;self.settings=Settings.load(root)
        self.ui_log=EventLog(root,'studio')
        self.ui_log.emit('studio_started',pid=os.getpid())
        self.history_signature=None;self.last_history_check=0.;self.library_notice=''
        pygame.display.init();pygame.font.init()
        self.display=pygame.display.set_mode(UI_SIZE,pygame.RESIZABLE)
        self.screen=pygame.Surface(UI_SIZE,depth=32)
        pygame.display.set_caption("Wonderland · 场景创作台")
        self.font=font(18);self.small=font(14);self.heading=font(34);self.label=font(12)
        self.prompt=EXAMPLES[0][1];self.composition=''
        self.focus=True;self.select_all=False;self.running=False;self.status='先描述一个地方，再走进去看看。'
        self.error=False;self.messages=queue.Queue();self.cancel=threading.Event();self.worker=None
        self.generator=None;self.started_at=None;self.log_open=False;self.log_scroll=0;self.job_path=None
        self.history=[];self.selected=None;self.preview=None;self.seed=42;self.alive=True
        self.games={};self.history_page=0
        self.refresh_history()
        if not self.history:
            cat=ensure_catalog(root)
            try:self.selected=save_world(compile_world(demo_spec(),cat.all()),root)
            finally:cat.close()
            self.refresh_history()
        for _,path in self.history:
            if self.select(path):break
        else:raise RuntimeError('已保存场景均无法加载，请查看 logs/studio.jsonl。')
        self.prompt=self.selected_prompt or EXAMPLES[0][1]
        pygame.key.start_text_input()
        self.update_ime_rect()

    def update_ime_rect(self):
        view=ui_viewport(self.display.get_size())
        size=pygame.display.get_window_size()
        sx=size[0]/self.display.get_width();sy=size[1]/self.display.get_height()
        pygame.key.set_text_input_rect(pygame.Rect((view.x+56*view.width/1280)*sx,
            (view.y+260*view.height/900)*sy,405*view.width/1280*sx,260*view.height/900*sy))

    def pointer_position(self,position):
        return ui_position(position,self.display.get_size(),pygame.display.get_window_size())

    def refresh_history(self,force=True):
        paths=list((self.root/'worlds').glob('*/world.json'))
        signature=tuple(sorted((str(p),p.stat().st_mtime_ns) for p in paths))
        if not force and signature==self.history_signature:return False
        self.history_signature=signature
        self.history=[]
        for path in sorted(paths,key=lambda p:p.stat().st_mtime,reverse=True):
            try:w=load_world(path)
            except Exception as exc:
                self.ui_log.emit('world_index_failed',world_path=str(path),**exception_fields(exc));continue
            self.history.append((w.title,path))
        self.history_page=min(getattr(self,'history_page',0),max(0,(len(self.history)-1)//3))
        self.ui_log.emit('history_refreshed',worlds=[dict(title=title,path=str(path)) for title,path in self.history])
        return True

    def poll_history(self,force=False):
        now=time.monotonic()
        if not force and now-self.last_history_check<2:return
        self.last_history_check=now
        before={path for _,path in self.history}
        if self.refresh_history(force=force):
            new=[title for title,path in self.history if path not in before]
            if new:self.library_notice='新场景已保存：'+new[0]
            elif force:self.library_notice='场景列表已刷新'

    def select(self,path):
        self.ui_log.emit('world_load_started',world_path=str(path))
        try:
            world=load_world(path)
            # Rendering stays on the main thread. The worker never touches SDL.
            target=pygame.Surface(UI_SIZE,depth=32)
            game=Game(world,self.root,target=target,present=False)
            preview_path=path.parent/'preview.png';game.screenshot(preview_path)
            preview=pygame.transform.scale(target.subsurface((0,78,1280,768)),(688,413))
        except Exception as exc:
            self.ui_log.emit('world_load_failed',world_path=str(path),**exception_fields(exc))
            self.status='场景已保存，但预览加载失败：'+safe_error(exc);self.error=True
            return False
        self.selected=path;self.preview=preview
        self.selected_title=world.title;self.selected_summary=world.plan.summary
        self.selected_prompt=world.prompt
        if not self.running:
            self.job_path=None
            for job_path in sorted((self.root/'data/jobs').glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True):
                try:job=json.loads(job_path.read_text())
                except (OSError,ValueError):continue
                if job.get('world_path')==str(path.relative_to(self.root)):
                    self.job_path=job_path;break
        self.ui_log.emit('world_loaded',world_path=str(path),title=world.title)
        pygame.display.set_caption("Wonderland · 场景创作台")
        return True

    def text(self,text,pos,which=None,color=INK):
        im=(which or self.font).render(text,True,color);self.screen.blit(im,pos)

    @property
    def preview_is_history(self):
        return self.running or self.error or self.prompt.strip()!=self.selected_prompt.strip()

    def wrap(self,text,rect,which=None,color=INK,line_height=28,max_lines=None,tail=True):
        which=which or self.font
        lines=[];line=''
        for char in text:
            if char=='\n' or which.size(line+char)[0]>rect.width:
                lines.append(line);line='' if char=='\n' else char
            else:line+=char
        lines.append(line)
        if max_lines:lines=lines[-max_lines:] if tail else lines[:max_lines]
        for i,line in enumerate(lines):self.text(line,(rect.x,rect.y+i*line_height),which,color)
        return rect.x+which.size(lines[-1])[0],rect.y+(len(lines)-1)*line_height

    def button(self,rect,text,primary=False,disabled=False):
        color=(211,214,198) if disabled else INK if primary else (224,225,207)
        if not disabled and rect.collidepoint(self.pointer_position(pygame.mouse.get_pos())):
            color=(65,89,70) if primary else (202,214,186)
        pygame.draw.rect(self.screen,color,rect,border_radius=8)
        im=self.font.render(text,True,CREAM if primary and not disabled else MUTED if disabled else INK)
        self.screen.blit(im,im.get_rect(center=rect.center))

    def start(self):
        if self.running:return
        if not self.prompt.strip():self.status='请输入一段场景描述。';self.error=True;return
        self.running=True;self.error=False;self.cancel=threading.Event()
        self.started_at=time.monotonic();self.log_scroll=0
        prompt=self.prompt;seed=self.seed
        self.status='正在准备场景…'
        def work():
            try:
                self.generator=Generator(self.settings,lambda msg:self.messages.put(('status',msg)),self.cancel)
                path=self.generator.generate(prompt,seed)
                self.messages.put(('done',path))
            except Cancelled as exc:self.messages.put(('cancelled',str(exc)))
            except Exception as exc:self.messages.put(('error',safe_error(exc)))
        self.worker=threading.Thread(target=work,daemon=True);self.worker.start()

    def drain_messages(self):
        if self.running and self.generator and self.generator.job_path:self.job_path=self.generator.job_path
        while not self.messages.empty():
            kind,value=self.messages.get()
            if kind=='status':self.status=value
            else:
                self.running=False
                if kind=='done':
                    if self.select(value):
                        self.refresh_history();self.error=False;self.focus=False
                        self.status='已完成，点击「开始探索」进入新场景。'
                elif kind=='cancelled':self.status='本次生成已取消。'+value;self.error=True
                else:self.status='本次生成失败，未产生新场景。'+value;self.error=True

    def diagnostic_lines(self):
        if not self.job_path:
            paths=sorted((self.root/'data/jobs').glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)
            if paths:self.job_path=paths[0]
        if not self.job_path:return ['还没有生成记录。']
        try:job=json.loads(self.job_path.read_text())
        except (OSError,ValueError):return ['正在读取任务记录…']
        lines=[f"任务：{self.job_path.stem}    状态：{job.get('stage','未知')}",
               f"描述：{job.get('prompt','')}"]
        if job.get('error'):lines.append('错误：'+job['error'])
        path=self.root/job.get('log_path',f'logs/{self.job_path.stem}.jsonl')
        lines.append('完整记录：'+str(path if path.exists() else self.job_path))
        if not path.exists():
            lines.append('这是旧版本任务，只有状态快照；新版任务会保留逐阶段日志。')
            return redact(lines)
        for line in path.read_text().splitlines():
            try:event=json.loads(line)
            except ValueError:continue
            stamp=datetime.fromtimestamp(event['time']).strftime('%H:%M:%S')
            kind=event['event']
            if kind=='stage':detail=event['detail']
            elif kind=='api_started':detail=f"调用 {event['kind']} · {event['model']}"
            elif kind=='api_completed':detail=f"调用完成 {event['kind']} · {event['duration_seconds']} 秒 · tokens {(event.get('usage') or {}).get('total_tokens','—')}"
            elif kind=='asset_reviewed':detail=f"素材检查 {event['need']} · {event['result']}"
            elif 'error' in event:detail=event['error']
            elif kind=='plan_ready':detail=f"计划：{event['plan']['title']} · 需补充 {len(event['plan']['missing_assets'])} 个素材"
            elif kind=='run_completed':detail='场景已保存：'+event['world_path']
            elif kind=='run_started':detail='开始生成'
            else:continue
            lines.append(f'{stamp}  {detail}')
        return redact(lines)

    def draw_log(self):
        pygame.draw.rect(self.screen,CREAM,(24,112,1232,718),border_radius=12)
        pygame.draw.rect(self.screen,INK,(24,112,1232,718),2,border_radius=12)
        self.text('生成日志',(48,134),self.heading)
        self.log_close_rect=pygame.Rect(1100,138,126,42);self.button(self.log_close_rect,'关闭 ×')
        self.text('滚轮翻阅 · F3 / Esc 关闭 · 完整 JSONL 保存在本地 logs 目录',(48,181),self.small,MUTED)
        lines=[]
        for entry in self.diagnostic_lines():
            line=''
            for char in entry:
                if char=='\n' or self.small.size(line+char)[0]>1170:
                    lines.append(line);line='' if char=='\n' else char
                else:line+=char
            lines.append(line)
        end=max(24,len(lines)-self.log_scroll)
        for i,line in enumerate(lines[max(0,end-24):end]):self.text(line,(48,221+i*24),self.small)

    def draw(self):
        s=self.screen;s.fill(CREAM)
        pygame.draw.circle(s,(83,115,72),(43,45),18)
        pygame.draw.line(s,CREAM,(35,52),(51,35),3)
        self.text('WONDERLAND',(76,16),self.heading)
        self.text('把想象中的地方，变成可以走进去的世界。',(78,62),self.small,MUTED)
        self.text('本地创作  /  LIMEZU 像素素材',(966,38),self.small,MUTED)
        pygame.draw.line(s,(206,211,190),(32,103),(1248,103))
        self.text('01  描述你的场景',(36,138),self.font)
        self.text('关键词也可以，细节越具体，世界越接近你的想象。',(36,175),self.small,MUTED)
        self.input_rect=pygame.Rect(36,218,456,284)
        pygame.draw.rect(s,(248,246,235),self.input_rect,border_radius=10)
        pygame.draw.rect(s,(130,153,109) if self.focus else (210,214,193),self.input_rect,2,border_radius=10)
        if self.select_all:pygame.draw.rect(s,(218,230,199),self.input_rect.inflate(-24,-24),border_radius=4)
        end=self.wrap(self.prompt,self.input_rect.inflate(-36,-36),max_lines=8)
        if self.focus and not self.running and pygame.time.get_ticks()%1000<500:
            pygame.draw.line(s,INK,(end[0]+2,end[1]+2),(end[0]+2,end[1]+23),1)
        if self.composition:self.text(self.composition,(55,472),self.small,(76,113,69))
        self.example_rects=[]
        for i,(label,_) in enumerate(EXAMPLES):
            r=pygame.Rect(36+i*153,518,143,36);self.button(r,label);self.example_rects.append(r)
        self.generate_rect=pygame.Rect(36,578,288,52)
        self.cancel_rect=pygame.Rect(340,578,152,52)
        self.button(self.generate_rect,'正在生成…' if self.running else '生成这个世界  ↗',True,self.running)
        self.button(self.cancel_rect,'取消' if self.running else '换一颗种子')
        self.text(f'SEED {self.seed}  ·  质量优先  ·  ⌘/Ctrl + Enter 生成',(36,645),self.small,MUTED)
        if self.running:
            elapsed=int(time.monotonic()-self.started_at)
            self.text(f'已运行 {elapsed//60:02d}:{elapsed%60:02d} · 可查看日志了解当前阶段',(36,670),self.small,MUTED)
        self.wrap(self.status,pygame.Rect(36,698,446,88),self.small,(155,66,52) if self.error else MUTED,22,4,tail=False)
        self.log_rect=pygame.Rect(36,795,218,36);self.button(self.log_rect,'查看生成日志  F3')
        self.text('02  走进世界',(528,138),self.font)
        if self.preview:
            pygame.draw.rect(s,(204,214,191),(528,180,688,413),border_radius=8)
            s.blit(self.preview,(528,180))
        if self.preview_is_history:
            pygame.draw.rect(s,(248,235,208),(528,180,688,32))
            self.text('历史场景预览 · 本次请求尚未生成新场景',(541,186),self.small,(138,83,39))
        self.text(self.selected_title,(528,614),self.font)
        self.wrap(self.selected_summary,pygame.Rect(528,650,490,64),self.small,MUTED,23,2,tail=False)
        self.play_rect=pygame.Rect(1054,612,162,52)
        self.button(self.play_rect,'继续探索 →' if self.selected in self.games else '开始探索 →',True)
        self.text('Enter 探索 · Esc 返回',(1054,676),self.small,MUTED)
        self.text('最近的世界',(528,727),self.small,MUTED)
        self.text(self.library_notice[:19],(649,730),self.small,MUTED)
        self.prev_rect=pygame.Rect(915,715,40,36);self.next_rect=pygame.Rect(1042,715,40,36)
        pages=max(1,(len(self.history)+2)//3)
        self.button(self.prev_rect,'‹',disabled=self.history_page==0)
        self.text(f'{self.history_page+1} / {pages}',(970,724),self.small)
        self.button(self.next_rect,'›',disabled=self.history_page+1>=pages)
        self.refresh_rect=pygame.Rect(1098,715,118,36);self.button(self.refresh_rect,'刷新 F5')
        self.history_rects=[]
        for i,(title,path) in enumerate(self.history[self.history_page*3:self.history_page*3+3]):
            r=pygame.Rect(528+i*234,761,220,44)
            self.button(r,title[:12]);self.history_rects.append((r,path))
        pygame.draw.line(s,(206,211,190),(32,844),(1248,844))
        self.text('WASD 移动 · E 进出房屋 · 生成后可离线探索',(36,861),self.small,MUTED)
        self.text('Artwork by LimeZu',(1070,861),self.small,MUTED)
        if self.log_open:self.draw_log()
        self.display=pygame.display.get_surface()
        view=ui_viewport(self.display.get_size())
        self.display.fill(CREAM)
        self.display.blit(pygame.transform.scale(self.screen,view.size),view.topleft)
        pygame.display.flip()

    def play(self):
        if not self.selected:return
        self.ui_log.emit('explore_clicked',world_path=str(self.selected))
        try:
            pygame.key.stop_text_input()
            game=self.games.get(self.selected)
            if game is None:
                game=Game(load_world(self.selected),self.root,target=self.display)
                self.games[self.selected]=game
            else:game.screen=self.display
            game.event_log=self.ui_log
            pygame.display.set_caption('Wonderland · '+game.world.title)
            self.ui_log.emit('exploration_started',world_path=str(self.selected))
            self.alive=game.run()
            self.ui_log.emit('exploration_finished',closed=game.closed,scene=game.scene_id)
        except Exception as exc:
            self.ui_log.emit('exploration_failed',**exception_fields(exc))
            self.status='进入场景失败：'+safe_error(exc);self.error=True
        finally:
            if self.alive:
                pygame.key.start_text_input()
                self.update_ime_rect()
                pygame.display.set_caption("Wonderland · 场景创作台")
            else:self.cancel.set()

    def run(self):
        clock=pygame.time.Clock()
        while self.alive:
            self.drain_messages()
            self.poll_history()
            self.draw()
            for event in pygame.event.get():
                if event.type==pygame.QUIT:self.cancel.set();self.alive=False
                elif event.type==pygame.WINDOWSIZECHANGED:
                    self.display=pygame.display.get_surface();self.update_ime_rect()
                elif event.type==pygame.KEYDOWN and event.key==pygame.K_F3:self.log_open=not self.log_open
                elif event.type==pygame.KEYDOWN and event.key==pygame.K_F2:
                    path=self.root/'screenshots'/f'studio_{int(time.time())}.png'
                    path.parent.mkdir(parents=True,exist_ok=True)
                    pygame.image.save(self.display,str(path))
                elif event.type==pygame.KEYDOWN and event.key==pygame.K_F5:self.poll_history(force=True)
                elif self.log_open:
                    if event.type==pygame.KEYDOWN and event.key==pygame.K_ESCAPE:self.log_open=False
                    elif event.type==pygame.MOUSEWHEEL:self.log_scroll=max(0,self.log_scroll+event.y*3)
                    elif event.type==pygame.MOUSEBUTTONDOWN and event.button==1 and self.log_close_rect.collidepoint(self.pointer_position(event.pos)):
                        self.log_open=False
                elif event.type==pygame.MOUSEBUTTONDOWN and event.button==1:
                    pos=self.pointer_position(event.pos);self.focus=self.input_rect.collidepoint(pos)
                    self.ui_log.emit('studio_click',position=list(event.pos),ui_position=list(pos),surface_size=list(self.display.get_size()),
                                     window_size=list(pygame.display.get_window_size()),play_rect=list(self.play_rect))
                    if self.generate_rect.collidepoint(pos):self.start()
                    elif self.log_rect.collidepoint(pos):self.log_open=True
                    elif self.refresh_rect.collidepoint(pos):self.poll_history(force=True)
                    elif self.prev_rect.collidepoint(pos):self.history_page=max(0,self.history_page-1)
                    elif self.next_rect.collidepoint(pos):self.history_page=min((len(self.history)-1)//3,self.history_page+1)
                    elif self.cancel_rect.collidepoint(pos):
                        if self.running:self.cancel.set();self.status='正在取消；已发出的 API 请求会完成后停止。'
                        else:self.seed=random.randrange(1,100000)
                    elif self.play_rect.collidepoint(pos) or pygame.Rect(528,180,688,413).collidepoint(pos):
                        self.play();break
                    else:
                        for r,(_,prompt) in zip(self.example_rects,EXAMPLES):
                            if r.collidepoint(pos) and not self.running:self.prompt=prompt;self.focus=True
                        for r,path in self.history_rects:
                            if r.collidepoint(pos):self.select(path)
                elif event.type==pygame.TEXTEDITING:self.composition=event.text
                elif event.type==pygame.TEXTINPUT and self.focus and not self.running:
                    self.prompt=(("" if self.select_all else self.prompt)+event.text)[:12000];self.composition='';self.select_all=False
                elif event.type==pygame.KEYDOWN:
                    command=event.mod & (pygame.KMOD_CTRL | pygame.KMOD_META)
                    if event.key==pygame.K_RETURN and command:self.start()
                    elif event.key==pygame.K_TAB:self.focus=not self.focus;self.select_all=False
                    elif event.key==pygame.K_RETURN and not self.focus:self.play();break
                    elif self.focus and not self.running:
                        if event.key==pygame.K_BACKSPACE:self.prompt='' if self.select_all else self.prompt[:-1];self.select_all=False
                        elif event.key==pygame.K_RETURN:self.prompt+='\n'
                        elif event.key==pygame.K_a and command:self.select_all=True
                        elif event.key==pygame.K_v and command:
                            try:self.prompt=(("" if self.select_all else self.prompt)+pygame.scrap.get_text())[:12000];self.select_all=False
                            except pygame.error:self.status='剪贴板不可用，可以直接输入或使用 prompt 文件。'
            clock.tick(30)
        pygame.quit()
