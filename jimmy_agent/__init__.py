"""Jimmy - a personal AI agent that learns from you and helps you."""

from .agent import Jimmy, main
from .brain import Brain
from .extractor import extract
from .learning_engine import LearningEngine
from .tools import Toolbox
from .voice import Voice

__version__ = "1.0.0"
__all__ = ["Jimmy", "Brain", "LearningEngine", "Toolbox", "Voice", "extract", "main"]
