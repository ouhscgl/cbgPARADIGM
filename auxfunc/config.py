#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
config.py -- one loader for configs/, with a per-machine overlay.

Every machine in the lab needs its own paths (nirx_data, emotiv_data, the
instruction video, monitor_index) while sharing everything else. Tracking
settings.json in git and editing it on each machine makes every `git pull`
either a conflict or a silent clobber of whoever fixed a path last.

So: `configs/settings.json` stays in git as the shared defaults, and each
machine may keep an untracked `configs/settings.local.json` holding only the
keys it overrides. This loader deep-merges the second over the first, which
means a key added upstream still reaches every machine on the next pull --
unlike untracking the whole file, where new keys never arrive.

The same applies to any config: profiles.json + profiles.local.json works too.

    settings.json        settings.local.json        result
    paths.nirx_data      paths.nirx_data            local wins
    paths.log_dir        (absent)                   shared value
    display.width        (absent)                   shared value
    (absent)             display.monitor_index      local value
"""

import json
import os

__all__ = ['load_config', 'config_dir', 'local_path_for', 'applied_overlays',
           'deep_merge']

# Overlay files actually used this process, for logging at startup.
_applied = []


def config_dir():
    """<repo>/configs, regardless of which subfolder the caller lives in."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, '..', 'configs'))


def local_path_for(filename, directory=None):
    """configs/settings.json -> configs/settings.local.json"""
    stem, ext = os.path.splitext(filename)
    return os.path.join(directory or config_dir(), f"{stem}.local{ext}")


def deep_merge(base, overlay):
    """Overlay wins. Dicts merge key by key; everything else is replaced.

    Lists are replaced wholesale on purpose: a machine overriding
    window_size means [420, 600], not [400, 545] with 420 mixed in.
    """
    if not isinstance(base, dict) or not isinstance(overlay, dict):
        return overlay
    merged = dict(base)
    for key, value in overlay.items():
        if key in merged:
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(filename, directory=None):
    """Load configs/<filename> and merge configs/<stem>.local.<ext> over it.

    The base file behaves like open(): a missing one raises FileNotFoundError
    and a malformed one raises json.JSONDecodeError, so existing callers keep
    their error handling. A missing overlay is normal and silent; a malformed
    overlay raises, because running with half a machine's paths is worse than
    not starting.
    """
    directory = directory or config_dir()
    with open(os.path.join(directory, filename), 'r', encoding='utf-8-sig') as handle:
        data = json.load(handle)

    overlay_path = local_path_for(filename, directory)
    if os.path.exists(overlay_path):
        with open(overlay_path, 'r', encoding='utf-8-sig') as handle:
            data = deep_merge(data, json.load(handle))
        if overlay_path not in _applied:
            _applied.append(overlay_path)
    return data


def applied_overlays():
    """Overlay files merged so far in this process (for the startup log)."""
    return list(_applied)
