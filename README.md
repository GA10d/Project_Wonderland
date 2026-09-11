<div align="center">

# Wonderland

### One prompt. A pixel world you can walk into.

**English** · [简体中文](README.zh-CN.md)

Zero-shot scene generation · Explorable interiors · Python + pygame-ce · OpenAI

</div>

Wonderland turns a short description into an **explorable 2D pixel world**: terrain, buildings, furnished interiors, solid obstacles, and doors you can walk up to and enter.

Describe a supermarket, an office, a demon's volcanic palace, or a cabin in the snow. Let the agent assemble the scene, then step inside.

![Wonderland running on macOS: a single prompt and its generated scene](docs/media/app-studio.png)

*The actual local app, with a scene generated from “雪山场景，有一个巨大的房屋，里面有壁炉和床” — “A snowy mountain scene with a huge house, with a fireplace and a bed inside.” The prototype UI currently uses Chinese.*

## Zero-shot, from description to exploration

**Your input is the description.** You do not need to place tiles, design a separate layout for each scene, or write scene-specific code.

The agent interprets the request, selects suitable assets, generates missing artwork when needed, and hands the plan to Python to build and validate the world. A curated asset library and layout rules provide the foundation; checks and retries are part of the pipeline. Here, zero-shot describes the user workflow, rather than a guarantee that every generation succeeds on its first attempt.

- **A place with an inside.** Buildings connect to furnished rooms through working entrances and exits.
- **Artwork on demand.** Reuse suitable local assets; generate, normalize, review, and index missing ones for future scenes.
- **Interaction included.** Walk with WASD, collide with solid objects, and press E at a doorway to enter or leave.
- **A persistent local world.** Reopen saved scenes and explore offline. Generation uses OpenAI APIs; rendering runs locally in Python.

```text
Your description → Scene plan → Reuse / generate assets → Build & validate → Explore
```

## One workflow, different worlds

These are screenshots from saved, playable scenes. English prompts below are translations of the Chinese requests. The gallery uses the game's renderer; the app screenshots were captured during live exploration. [Capture details](docs/media/README.md)

### A supermarket

> “Generate a Joja supermarket scene like Stardew Valley.”

| Outside | Inside |
| :---: | :---: |
| ![Blue Joja supermarket with an accessible front door](docs/media/supermarket-exterior.png) | ![Supermarket interior with four stocked shelves and a checkout counter](docs/media/supermarket-interior.png) |

A blue storefront opens into a shop with stocked shelves, a checkout counter, and space to walk around.

### An office

> “I want an urban scene with an office I can enter, filled with office supplies.”

| Outside | Inside |
| :---: | :---: |
| ![Office building on an urban plaza](docs/media/office-exterior.png) | ![Office interior with four workstations and support equipment](docs/media/office-interior.png) |

An office building connects to a furnished workspace with computers, desks, chairs, equipment, and a clear central aisle.

### A volcanic demon palace

> “A volcanic scene filled with lava, with a demon's residence in the middle. Enter it to find the demon king's palace.”

| Outside | Inside |
| :---: | :---: |
| ![Demon castle surrounded by a lava landscape](docs/media/volcano-exterior.png) | ![Demon king's throne and furnishings inside the palace](docs/media/volcano-interior.png) |

Lava terrain, a dark castle, and a throne room come together in one connected scene.

### A house in the snow

> “A snowy mountain scene with a huge house, with a fireplace and a bed inside.”

| Outside · wider view | Inside |
| :---: | :---: |
| ![A large wooden house with snowy peaks behind it](docs/media/snow-exterior.png) | ![Warm cabin interior with a bed and fireplace](docs/media/snow-interior.png) |

Snow-covered ground and mountain scenery surround a large wooden house with a furnished interior.

## See it running

Here is a second zero-shot example generated from “Generate a cyberpunk world”: approach the building, press **E**, and enter its room. These frames were saved from the running macOS app.

| Approach the door | Explore the interior |
| :---: | :---: |
| ![Live gameplay with the E-to-enter prompt at a neon apartment building](docs/media/app-explore.png) | ![Live gameplay after entering the apartment](docs/media/app-interior.png) |

| Control | Action |
| :--- | :--- |
| WASD / Arrow keys | Move |
| E, facing a doorway | Enter / leave |
| Esc | Return to the studio |
| F2 | Save a screenshot in the studio or game |

## Try it locally

The current demo is developed and tested on **macOS**, with **Python 3.11+**. New generation requires an OpenAI API key and access to the text/vision and image models configured in `config.toml`.

```bash
git clone https://github.com/GA10d/Project_Wonderland.git
cd Project_Wonderland
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
```

1. Add your licensed LimeZu asset packs under `assets/raw/`, following the paths in [the asset manifest](assets/manifests/limezu.json). The asset packs are not included in this repository. See [asset setup](assets/README.md).
2. Create `key.env` in the project root with `OPENAI_API_KEY=your_key_here`. Choose models available to your account in `config.toml`.
3. Import the assets and launch:

```bash
.venv/bin/python -m wonderland assets --import
.venv/bin/python -m wonderland
```

After setup, you can also double-click `Launch_Wonderland.command`. Enter a description, generate a world, then click **开始探索** (“Start exploring”).

Keys, source artwork, generated assets, worlds, and logs stay out of Git. The screenshots in `docs/media/` are included for this showcase.

[Detailed setup and development guide (中文)](docs/GUIDE.zh-CN.md) · [Architecture](lectotype/SCENE_GENERATOR_PLAN.md) · [Tilemap design](lectotype/README.md)

## Credits

Pixel artwork uses licensed assets by **[LimeZu](https://limezu.itch.io/)** alongside generated assets. Original asset packs are not redistributed here. Joja / Stardew Valley is shown as a fan-inspired example; Wonderland is not affiliated with or endorsed by Stardew Valley or its creators.

## An early demo, with more to come

**This is an early demo.** We will continue refining visual consistency, scene composition, asset coverage, reliability, and the overall experience. The current scope is exploration, collisions, and room transitions; it does not yet include NPC simulation or a full game rules system. Generation currently prioritizes quality over latency.

**A possible next direction: real-time scene generation for AI-led tabletop role-playing games.** As a game master narrates a new location or players change the story, Wonderland could turn that description into a shared place to explore. This is a future direction; the current demo is the starting point.
