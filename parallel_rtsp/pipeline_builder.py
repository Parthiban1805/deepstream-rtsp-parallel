import sys
import os
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst
import configparser
import math

os.environ["USE_NEW_NVSTREAMMUX"] = "yes"

from common.platform_info import PlatformInfo
import config


def cb_newpad(decodebin, decoder_src_pad, data):
    caps = decoder_src_pad.get_current_caps()
    if not caps:
        return

    gststruct = caps.get_structure(0)
    gstname = gststruct.get_name()
    source_bin = data
    features = caps.get_features(0)

    if "video" in gstname:
        if features.contains(config.GST_CAPS_FEATURES_NVMM):
            bin_ghost_pad = source_bin.get_static_pad("src")
            if not bin_ghost_pad.set_target(decoder_src_pad):
                sys.stderr.write(
                    f"Failed to link decoder src pad to source bin ghost pad for {source_bin.name}\n"
                )
        else:
            sys.stderr.write("Error: Decodebin did not pick NVIDIA decoder plugin.\n")


