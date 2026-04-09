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


def create_inference_branch(pipeline, index, source_pad, config_file, unique_id):
    """
    Each sub-mux must use a UNIQUE sink pad index across the whole pipeline.
    So stream 0 uses sub_mux.sink_0, stream 1 uses sub_mux.sink_1, etc.
    Then demux must read src_<same_index>.
    """
    q1 = Gst.ElementFactory.make("queue", f"sub_q1_{index}")
    mux = Gst.ElementFactory.make("nvstreammux", f"sub_mux_{index}")
    pgie = Gst.ElementFactory.make("nvinfer", f"sub_pgie_{index}")
    demux = Gst.ElementFactory.make("nvstreamdemux", f"sub_demux_{index}")
    q2 = Gst.ElementFactory.make("queue", f"sub_q2_{index}")

    if not q1 or not mux or not pgie or not demux or not q2:
        sys.stderr.write(f"Failed to create inference elements for branch {index}\n")
        return None

    # New nvstreammux safe properties
    mux.set_property("batch-size", 1)
    mux.set_property("batched-push-timeout", 40000)

    pgie.set_property("config-file-path", config_file)
    pgie.set_property("unique-id", unique_id)

    print(f"[INFO] Stream {index}: config={config_file}, unique-id={unique_id}")

    for elem in [q1, mux, pgie, demux, q2]:
        pipeline.add(elem)

    if source_pad.link(q1.get_static_pad("sink")) != Gst.PadLinkReturn.OK:
        sys.stderr.write(f"Failed to link source -> q1 for stream {index}\n")
        return None

    # CRITICAL FIX:
    # use sink_<index>, not sink_0 for every sub-mux
    sub_mux_sinkpad = mux.request_pad_simple(f"sink_{index}")
    if not sub_mux_sinkpad:
        sys.stderr.write(f"Failed to request sink_{index} from sub mux for stream {index}\n")
        return None

    if q1.get_static_pad("src").link(sub_mux_sinkpad) != Gst.PadLinkReturn.OK:
        sys.stderr.write(f"Failed to link q1 -> sub mux for stream {index}\n")
        return None

    if not mux.link(pgie):
        sys.stderr.write(f"Failed to link sub mux -> pgie for stream {index}\n")
        return None

    if not pgie.link(demux):
        sys.stderr.write(f"Failed to link pgie -> demux for stream {index}\n")
        return None

    # CRITICAL FIX:
    # demux output pad must match the same stream index
    demux_srcpad = demux.request_pad_simple(f"src_{index}")
    if not demux_srcpad:
        sys.stderr.write(f"Failed to request src_{index} from demux for stream {index}\n")
        return None

    if demux_srcpad.link(q2.get_static_pad("sink")) != Gst.PadLinkReturn.OK:
        sys.stderr.write(f"Failed to link demux -> q2 for stream {index}\n")
        return None

    return q2.get_static_pad("src")
