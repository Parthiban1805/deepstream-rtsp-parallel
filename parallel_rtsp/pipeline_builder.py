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


def create_source_bin(index, uri):
    bin_name = f"source-bin-{index:02d}"
    nbin = Gst.Bin.new(bin_name)
    if not nbin:
        sys.stderr.write(f"Unable to create source bin {bin_name}\n")
        return None

    if uri.startswith("v4l2://"):
        device = uri.replace("v4l2://", "")

        src = Gst.ElementFactory.make("v4l2src", f"v4l2src-{index}")
        jpegdec = Gst.ElementFactory.make("jpegdec", f"jpegdec-{index}")
        conv = Gst.ElementFactory.make("nvvideoconvert", f"conv-{index}")

        if not src or not jpegdec or not conv:
            sys.stderr.write(f"Unable to create v4l2 source elements for stream {index}\n")
            return None

        src.set_property("device", device)

        Gst.Bin.add(nbin, src)
        Gst.Bin.add(nbin, jpegdec)
        Gst.Bin.add(nbin, conv)

        if not src.link(jpegdec):
            sys.stderr.write(f"Failed to link v4l2src -> jpegdec for stream {index}\n")
            return None

        if not jpegdec.link(conv):
            sys.stderr.write(f"Failed to link jpegdec -> nvvideoconvert for stream {index}\n")
            return None

        ghost_pad = Gst.GhostPad.new("src", conv.get_static_pad("src"))
        nbin.add_pad(ghost_pad)

    else:
        uri_decode_bin = Gst.ElementFactory.make("uridecodebin", f"uri-decode-bin-{index}")
        if not uri_decode_bin:
            sys.stderr.write(f"Unable to create uridecodebin for stream {index}\n")
            return None

        uri_decode_bin.set_property("uri", uri)
        uri_decode_bin.connect("pad-added", cb_newpad, nbin)

        Gst.Bin.add(nbin, uri_decode_bin)
        nbin.add_pad(Gst.GhostPad.new_no_target("src", Gst.PadDirection.SRC))

    return nbin
