from __future__ import annotations

import math
import os
import random
import time
from pathlib import Path

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame

from .config import CELL, ROOT
from .models import World
from .world import PLAYER_HALF, PLAYER_HALF_Y, can_stand, entity_rect, intersects, solid_rects, tile_mask

CREAM=(238,235,217)
INK=(40,57,49)
MUTED=(114,125,105)


def font(size):
    for path in ("/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/STHeiti Light.ttc",
                 "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"):
        if Path(path).exists(): return pygame.font.Font(path,size)
    return pygame.font.SysFont("sans",size)


class Game:
    def __init__(self, world: World, root: Path=ROOT, size=(1280,900), headless=False,
                 target: pygame.Surface | None=None, present=True):
        if headless:
            os.environ.setdefault("SDL_VIDEODRIVER","dummy")
            os.environ.setdefault("SDL_AUDIODRIVER","dummy")
        pygame.display.init();pygame.font.init()
        self.screen=target if target is not None else pygame.display.set_mode(size,pygame.RESIZABLE)
        self.present=present
        if present:pygame.display.set_caption("Wonderland · 由描述生长的世界")
        self.root,self.world=root,world
        self.scene_id=world.player_scene
        self.x,self.y=world.scenes[self.scene_id].spawn
        self.facing="up"
        self.moving=False
        self.walk_time=0.
        self.debug=False
        self.interaction_armed=True
        self.transition_time=0.
        self.images={aid:pygame.image.load(str(root/a.image)).convert_alpha() for aid,a in world.assets.items()}
        self.font=font(17);self.small=font(13);self.title_font=font(25)
        self.backgrounds={};self.rect_cache={s.id:solid_rects(s,world.assets) for s in world.scenes.values()}
        self.toast="走到门前，面向门口，按 E 探索室内"
        self.closed=False
        self.event_log=None

    @property
    def scene(self): return self.world.scenes[self.scene_id]

    def set_scene(self,scene_id,position=None):
        self.scene_id=scene_id
        self.x,self.y=position or self.scene.spawn
        self.walk_time=0;self.moving=False

    def move(self,dx,dy,dt):
        self.moving=bool(dx or dy)
        if not self.moving:return
        if abs(dx)>abs(dy):self.facing="right" if dx>0 else "left"
        else:self.facing="down" if dy>0 else "up"
        length=math.hypot(dx,dy)
        travel=155*min(dt,.1)
        steps=max(1,math.ceil(travel/4))
        vx,vy=dx/length*travel/steps,dy/length*travel/steps
        for _ in range(steps):
            if can_stand(self.scene,self.world.assets,self.x+vx,self.y,self.rect_cache[self.scene_id]):self.x+=vx
            if can_stand(self.scene,self.world.assets,self.x,self.y+vy,self.rect_cache[self.scene_id]):self.y+=vy
        self.walk_time+=dt

    def portal_rect(self,portal):
        x,y,w,h=portal.rect
        # Legacy snapshots stop the exit zone before the walkable doorway.
        # Keep E available all the way to the bottom edge, including old worlds.
        if self.scene.kind=='indoor' and portal.facing=='down' and y>=(self.scene.height-2)*CELL:
            h=max(h,self.scene.height*CELL-y)
        return x,y,w,h

    def active_portal(self):
        # Player center, not the whole sprite, must be inside the approach zone.
        for p in self.scene.portals:
            if intersects((self.x-1,self.y-1,2,2),self.portal_rect(p)) and self.facing==p.facing:return p
        return None

    def interact(self):
        if not self.interaction_armed:return False
        self.interaction_armed=False
        p=self.active_portal()
        if not p:return False
        if not can_stand(self.world.scenes[p.target_scene],self.world.assets,*p.target_spawn,
                         self.rect_cache[p.target_scene]):return False
        source=self.scene_id
        self.set_scene(p.target_scene,p.target_spawn)
        if self.event_log:self.event_log.emit('portal_used',source=source,target=self.scene_id,portal=p.id)
        self.facing="up" if self.scene.kind=="indoor" else "down"
        self.transition_time=.3
        self.toast=self.scene.name
        return True

    def release_interact(self):self.interaction_armed=True

    def background(self):
        if self.scene_id in self.backgrounds:return self.backgrounds[self.scene_id]
        s=self.scene
        # Cocoa's display format includes an alpha mask. convert() inherits that
        # mask without enabling alpha blending; tile blits can then leave alpha=0
        # under visible RGB pixels. Keep the opaque map explicitly alpha-free so
        # copying it to the window writes alpha=255 before sprites are composited.
        bg=pygame.Surface((s.width*CELL,s.height*CELL),depth=32)
        bg.fill((42,48,46))
        for y,row in enumerate(s.terrain):
            for x,kind in enumerate(row):
                pos=(x*CELL,y*CELL)
                if kind=='path' and self.world.plan.biome=='urban':
                    tile=self.images['tile.office_floor']
                elif kind in ("path","water"):
                    tile=self.images[f"auto.{kind}.{tile_mask(s,x,y)}"]
                    if self.world.plan.ground_asset_id:
                        tile=tile.copy();ground=self.images[self.world.plan.ground_asset_id]
                        for gy in range(CELL):
                            for gx in range(CELL):
                                r,g,b,_=tile.get_at((gx,gy))
                                if g>r*1.2 and g>b*1.15:tile.set_at((gx,gy),ground.get_at((gx,gy)))
                elif kind=="wall":
                    tile=self.images["tile.wall_top" if y in (0,s.height-1) else "tile.wall_bottom"]
                else:tile=self.images["tile.floor" if kind=="floor" else "tile.grass" if kind=="grass" else kind]
                bg.blit(tile,pos)
        if s.kind=="outdoor":
            rng=random.Random(self.world.seed+801)
            # Sparse tiny blades at the same 2px density as the supplied artwork.
            for _ in range(s.width*s.height*2):
                x,y=rng.randrange(bg.width//2)*2,rng.randrange(bg.height//2)*2
                if s.terrain[y//CELL][x//CELL]!="grass":continue
                color=rng.choice([(81,154,85),(61,132,77),(93,157,87)])
                pygame.draw.line(bg,color,(x,y),(x+2,y-2),2)
                if rng.random()<.07:
                    pygame.draw.rect(bg,(190,196,112),(x+2,y-4,2,2))
        else:
            # Architectural depth: wall caps and a recessed doorway.
            pygame.draw.rect(bg,(55,49,47),(0,0,bg.width,6))
            pygame.draw.rect(bg,(84,74,62),(0,0,6,bg.height))
            pygame.draw.rect(bg,(84,74,62),(bg.width-6,0,6,bg.height))
            pygame.draw.rect(bg,(185,177,151),(6,2*CELL,CELL-6,bg.height-3*CELL))
            pygame.draw.rect(bg,(185,177,151),(bg.width-CELL,2*CELL,CELL-6,bg.height-3*CELL))
            pygame.draw.rect(bg,(85,65,48),(8*CELL,15*CELL,2*CELL,4))
        self.backgrounds[s.id]=bg
        return bg

    def camera(self,viewport):
        s=self.scene
        if s.kind=="indoor":return (s.width*CELL-viewport.width)/2,(s.height*CELL-viewport.height)/2
        # Frame nearby architecture without wasting most of the viewport above a small cabin.
        buildings=[e for e in s.entities if self.world.assets[e.asset_id].category=='building']
        nearest=min(buildings,key=lambda e:(e.x-self.x)**2+(e.y-self.y)**2,default=None)
        look_ahead=64
        if nearest and math.hypot(nearest.x-self.x,nearest.y-self.y)<700:
            look_ahead=min(240,max(64,self.world.assets[nearest.asset_id].size[1]/2))
        cx=self.x-viewport.width/2
        cy=self.y-viewport.height/2-look_ahead
        return max(0,min(s.width*CELL-viewport.width,cx)),max(0,min(s.height*CELL-viewport.height,cy))

    def draw_text(self,text,x,y,which=None,color=INK):
        im=(which or self.font).render(text,True,color);self.screen.blit(im,(x,y));return im.get_rect(topleft=(x,y))

    def draw(self,dt=0):
        screen=self.screen;w,h=screen.get_size()
        screen.fill(CREAM)
        view=pygame.Rect(0,78,w,h-132)
        screen.set_clip(view)
        screen.fill((37,48,42),view)
        camx,camy=self.camera(view)
        origin=(int(-camx),int(view.y-camy))
        bg=self.background();screen.blit(bg,origin)
        entries=[]
        for e in self.scene.entities:
            a=self.world.assets[e.asset_id]
            entries.append((e.y,0,e.id,self.images[a.id],(e.x-a.anchor[0],e.y-a.anchor[1])))
        frame=str(int(self.walk_time*10)%6) if self.moving else "idle"
        player_id=f"player.{self.facing}.{frame}"
        player=self.images[player_id];anchor=self.world.assets[player_id].anchor
        # Small grounded shadow, independent from the transparent character canvas.
        pygame.draw.ellipse(screen,(55,99,59),(int(self.x-camx-12),int(self.y-camy+view.y-3),24,8))
        entries.append((self.y,1,"player",player,(self.x-anchor[0],self.y-anchor[1])))
        for _,_,_,image,pos in sorted(entries,key=lambda row:row[:3]):
            screen.blit(image,(round(pos[0]-camx),round(pos[1]-camy+view.y)))
        if self.debug:
            for r in self.rect_cache[self.scene_id]:pygame.draw.rect(screen,(237,91,93),(r[0]-camx,r[1]-camy+view.y,r[2],r[3]),1)
            for p in self.scene.portals:
                px,py,pw,ph=self.portal_rect(p)
                pygame.draw.rect(screen,(235,207,89),(px-camx,py-camy+view.y,pw,ph),2)
            pygame.draw.rect(screen,(255,250,220),(self.x-camx-PLAYER_HALF,self.y-camy+view.y-PLAYER_HALF_Y,PLAYER_HALF*2,PLAYER_HALF_Y*2),1)
        p=self.active_portal()
        if p:
            label=self.font.render("E  ·  "+p.label,True,CREAM)
            r=pygame.Rect(0,0,label.width+32,44);r.midbottom=(int(self.x-camx),int(self.y-camy+view.y-55))
            pygame.draw.rect(screen,INK,r,border_radius=10);screen.blit(label,(r.x+16,r.y+10))
        if self.transition_time>0:
            self.transition_time=max(0,self.transition_time-dt)
            veil=pygame.Surface(view.size,pygame.SRCALPHA);veil.fill((27,35,29,int(170*self.transition_time/.3)));screen.blit(veil,view.topleft)
        screen.set_clip(None)
        pygame.draw.line(screen,(210,214,194),(0,77),(w,77))
        pygame.draw.circle(screen,(82,110,73),(32,35),13)
        pygame.draw.line(screen,CREAM,(27,40),(36,29),2)
        self.draw_text("WONDERLAND",56,14,self.title_font)
        self.draw_text("由描述生长的世界",57,46,self.small,MUTED)
        self.draw_text(self.scene.name,330,19,self.font)
        self.draw_text("室内" if self.scene.kind=="indoor" else "室外 · 自由探索",330,45,self.small,MUTED)
        tag=f"SEED {self.world.seed}  /  {len(self.world.scenes)} SCENES"
        self.draw_text(tag,max(700,w-235),30,self.small,MUTED)
        pygame.draw.rect(screen,CREAM,(0,h-54,w,54))
        self.draw_text("W A S D / 方向键  移动     E  进出     F1  碰撞标记     F2  保存画面",24,h-36,self.small)
        self.back_rect=pygame.Rect(w-163,h-45,151,34)
        pygame.draw.rect(screen,(224,225,207),self.back_rect,border_radius=6)
        self.draw_text("Esc  返回创作台",w-150,h-36,self.small,INK)
        if self.present:pygame.display.flip()

    def screenshot(self,path: Path):
        path.parent.mkdir(parents=True,exist_ok=True);self.draw();pygame.image.save(self.screen,str(path))

    def run(self):
        clock=pygame.time.Clock();running=True
        while running:
            dt=clock.tick(60)/1000
            tapped=set()
            for event in pygame.event.get():
                if event.type==pygame.QUIT:self.closed=True;running=False
                elif event.type==pygame.KEYDOWN:
                    tapped.add(event.key)
                    if event.key==pygame.K_ESCAPE:running=False
                    elif event.key==pygame.K_e:self.interact()
                    elif event.key==pygame.K_F1:self.debug=not self.debug
                    elif event.key==pygame.K_F2:self.screenshot(self.root/"screenshots"/f"{self.scene_id}_{int(time.time())}.png")
                elif event.type==pygame.KEYUP and event.key==pygame.K_e:self.release_interact()
                elif event.type==pygame.MOUSEBUTTONDOWN and event.button==1:
                    ww,wh=pygame.display.get_window_size()
                    pos=(event.pos[0]*self.screen.get_width()/ww,event.pos[1]*self.screen.get_height()/wh)
                    if getattr(self,'back_rect',pygame.Rect(0,0,0,0)).collidepoint(pos):running=False
            if not running:break
            keys=pygame.key.get_pressed()
            # A quick down/up arriving within one frame must still move one step.
            def held(*codes):return any(keys[code] or code in tapped for code in codes)
            dx=int(held(pygame.K_d,pygame.K_RIGHT))-int(held(pygame.K_a,pygame.K_LEFT))
            dy=int(held(pygame.K_s,pygame.K_DOWN))-int(held(pygame.K_w,pygame.K_UP))
            self.move(dx,dy,dt);self.draw(dt)
        return not self.closed
