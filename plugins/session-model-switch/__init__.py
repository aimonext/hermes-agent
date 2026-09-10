"""Hermes plugin: session-model-switch

Per-session private/normal model router. See switcher.py for logic and PLAN.md for design.
"""

try:
    from .switcher import on_pre_gateway_dispatch  # type: ignore
except ImportError:
    from switcher import on_pre_gateway_dispatch  # type: ignore  # fallback for direct import

def register(ctx):
    """Called by PluginManager — register pre_gateway_dispatch hook."""
    ctx.register_hook("pre_gateway_dispatch", on_pre_gateway_dispatch)
