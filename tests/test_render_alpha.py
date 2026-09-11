import os
import subprocess
import sys

import pygame
import pytest

from wonderland.config import ROOT
from wonderland.runtime import Game
from wonderland.world import compile_world, demo_spec


def test_map_stays_opaque_when_composited_into_rgba_window(assets):
    game=Game(compile_world(demo_spec(),assets),headless=True)
    game.set_scene('interior_0')
    background=game.background()
    assert background.get_masks()[3]==0
    # Cocoa windows have an alpha mask, unlike the dummy driver's window.
    window=pygame.Surface(background.get_size(),pygame.SRCALPHA,32)
    window.blit(background,(0,0))
    pos=(200,300)
    floor=window.get_at(pos)
    assert floor.a==255
    for aid in ('furniture.lamp','furniture.cabinet','player.down.idle'):
        sprite=game.images[aid]
        assert sprite.get_at((0,0)).a==0
        window.blit(background,(0,0));window.blit(sprite,pos)
        assert window.get_at(pos)==floor


def test_transparent_pixels_preserve_floor_but_real_black_pixels_remain_black(assets):
    game=Game(compile_world(demo_spec(),assets),headless=True)
    game.set_scene('interior_0')
    target=pygame.Surface(game.background().get_size(),pygame.SRCALPHA,32)
    target.blit(game.background(),(0,0));floor=target.get_at((200,300))
    sprite=pygame.Surface((2,1),pygame.SRCALPHA,32)
    sprite.set_at((0,0),(0,0,0,0));sprite.set_at((1,0),(0,0,0,255))
    target.blit(sprite,(200,300))
    assert target.get_at((200,300))==floor
    assert target.get_at((201,300))==(0,0,0,255)


@pytest.mark.skipif(sys.platform!='darwin' or os.getenv('WONDERLAND_NATIVE_TESTS')!='1',
                    reason='Enable WONDERLAND_NATIVE_TESTS=1 to open a real macOS window.')
def test_native_cocoa_window_has_no_transparent_holes_after_drawing():
    # Run outside conftest's dummy driver: the defect depends on the real window
    # pixel format and cannot be reproduced by dummy-window-only tests.
    env=os.environ.copy();env.pop('SDL_VIDEODRIVER',None);env.pop('SDL_AUDIODRIVER',None)
    script='''
import pygame
from wonderland.catalog import Catalog
from wonderland.runtime import Game
from wonderland.world import compile_world, demo_spec
from wonderland.studio import Studio
cat=Catalog()
try: world=compile_world(demo_spec(),cat.all())
finally: cat.close()
game=Game(world)
try:
    assert pygame.display.get_driver()=='cocoa'
    for scene_id in ('outdoor','interior_0'):
        game.set_scene(scene_id)
        game.draw()
        pixels=pygame.image.tobytes(game.screen,'RGBA')
        assert set(pixels[3::4])=={255}, 'Visible frame contains transparent holes'
    original_set_mode=pygame.display.set_mode
    def constrained_mode(size,*args,**kwargs):
        return original_set_mode((size[0],min(size[1],843)),*args,**kwargs)
    pygame.display.set_mode=constrained_mode
    studio=Studio()
    studio.draw()
    assert set(pygame.image.tobytes(studio.screen,'RGBA')[3::4])=={255}
    assert set(pygame.image.tobytes(studio.display,'RGBA')[3::4])=={255}
    display=studio.display
    assert studio.select(studio.selected)
    studio.draw()
    assert pygame.display.get_surface() is display
finally: pygame.quit()
'''
    result=subprocess.run([sys.executable,'-c',script],cwd=ROOT,env=env,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
