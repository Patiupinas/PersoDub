"""The voice engines this app has, registered once per process in base.py's
registry: Qwen3-TTS on this computer.

Here, in the package, so importing any engine module registers it: a remade
line (app/qwen_pipeline.resynth_one_line) reads the registry, and must not
depend on an API module having been imported first.
"""
from app.engines.base import register_engine
from app.engines.qwen_tts import QwenTTSEngine
from app.engines.silero_ru import SileroRuEngine
from app.engines.voxcpm2_ru import VoxCPM2RuEngine
from app.engines.voxcpm2_expressive_ru import VoxCPM2ExpressiveRuEngine

register_engine(QwenTTSEngine())
register_engine(SileroRuEngine())
register_engine(VoxCPM2RuEngine())
register_engine(VoxCPM2ExpressiveRuEngine())
