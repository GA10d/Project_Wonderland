import shutil

import pygame
import pytest

from wonderland.config import ROOT
from wonderland.runtime import Game
from wonderland.studio import Studio, ui_position, ui_viewport
from wonderland.world import compile_world, demo_spec, save_world


@pytest.fixture
def studio_root(tmp_path,assets):
    for asset in assets.values():
        target=tmp_path/asset.image;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(ROOT/asset.image,target)
    save_world(compile_world(demo_spec(),assets),tmp_path)
    return tmp_path


def test_preview_exploration_and_return_do_not_recreate_window(studio_root,monkeypatch):
    set_mode=pygame.display.set_mode;calls=[]
    def recorded(*args,**kwargs):
        calls.append(args);return set_mode(*args,**kwargs)
    monkeypatch.setattr(pygame.display,'set_mode',recorded)
    studio=Studio(studio_root)
    display=studio.display
    assert len(calls)==1
    assert studio.select(studio.selected)
    visited=[]
    def explore(game):
        assert game.screen is display
        visited.append((game,game.scene_id))
        game.set_scene('interior_0')
        return True
    monkeypatch.setattr(Game,'run',explore)
    studio.play();studio.draw();studio.play();studio.draw()
    assert len(calls)==1
    assert visited[0][0] is visited[1][0]
    assert visited[1][1]=='interior_0'


@pytest.mark.parametrize('size',[(1280,900),(1000,650),(1700,900),(720,1050)])
def test_visible_explore_button_responds_after_resize(studio_root,monkeypatch,size):
    studio=Studio(studio_root)
    studio.display=pygame.display.set_mode(size,pygame.RESIZABLE)
    studio.draw()
    view=ui_viewport(size)
    # Click the rendered button center, including the UI's letterbox offset.
    point=(round(view.x+studio.play_rect.centerx*view.width/1280),
           round(view.y+studio.play_rect.centery*view.height/900))
    # The center can land on a cream text glyph; sample the button's solid fill.
    fill_point=(round(view.x+(studio.play_rect.left+12)*view.width/1280),
                round(view.y+(studio.play_rect.top+12)*view.height/900))
    assert studio.display.get_at(fill_point)[:3]!=studio.screen.get_at((0,0))[:3]
    opened=[]
    monkeypatch.setattr(Game,'run',lambda game:opened.append(game.world.id) or False)
    pygame.event.clear()
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN,button=1,pos=point))
    pygame.event.post(pygame.event.Event(pygame.QUIT))  # ensures a failed click cannot hang the test
    studio.run()
    assert opened==[studio.selected.parent.name]


def test_retina_window_points_map_to_same_ui_coordinates():
    for point in ((0,0),(567,400),(1135,638)):
        normal=ui_position(point,(1280,900),(1280,900))
        retina=ui_position(point,(2560,1800),(1280,900))
        assert normal==retina
