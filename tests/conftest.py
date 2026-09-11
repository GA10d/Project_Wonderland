import os
os.environ['SDL_VIDEODRIVER']='dummy'
os.environ['SDL_AUDIODRIVER']='dummy'
os.environ['PYGAME_HIDE_SUPPORT_PROMPT']='1'

import pytest
from wonderland.catalog import Catalog
from wonderland.config import ROOT


@pytest.fixture(scope='session')
def assets():
    if not (ROOT/'data/assets.sqlite').exists():
        pytest.skip('Run python -m wonderland assets --import with the licensed local art first.')
    c=Catalog()
    try:return c.all()
    finally:c.close()
