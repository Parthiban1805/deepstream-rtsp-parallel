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


def build_pipeline(number_sources, args):
    platform_info = PlatformInfo()

    pipeline = Gst.Pipeline()
    if not pipeline:
        sys.stderr.write("Unable to create Pipeline\n")
        return None

    main_streammux = Gst.ElementFactory.make("nvstreammux", "main-stream-muxer")
    if not main_streammux:
        sys.stderr.write("Unable to create main nvstreammux\n")
        return None

    pipeline.add(main_streammux)

    is_live = any(
        args[i + 1].startswith(("rtsp://", "v4l2://"))
        for i in range(number_sources)
    )

    # Main downstream mux: adaptive batching OFF through config file
    main_streammux.set_property("batch-size", number_sources)
    main_streammux.set_property("batched-push-timeout", 40000)
    main_streammux.set_property("config-file-path", config.MAIN_MUX_CONFIG_FILE)

    for i in range(number_sources):
        source_bin = create_source_bin(i, args[i + 1])
        if not source_bin:
            return None

        pipeline.add(source_bin)

        srcpad = source_bin.get_static_pad("src")
        if not srcpad:
            sys.stderr.write(f"Unable to get src pad for source bin {i}\n")
            return None

        if i in [0, 1]:
            print(f"--> Assigning PeopleNet inference to Stream {i}")
            branch_out_pad = create_inference_branch(
                pipeline, i, srcpad, config.PGIE_PEOPLENET_CONFIG_FILE, 10 + i
            )

        elif i in [2, 3, 4]:
            print(f"--> Assigning TrafficCamNet inference to Stream {i}")
            branch_out_pad = create_inference_branch(
                pipeline, i, srcpad, config.PGIE_TRAFFICCAMNET_CONFIG_FILE, 10 + i
            )

        else:
            print(f"--> No inference assigned to Stream {i} (Pass-through)")
            q_pass = Gst.ElementFactory.make("queue", f"pass_q_{i}")
            if not q_pass:
                sys.stderr.write(f"Failed to create pass queue for stream {i}\n")
                return None

            pipeline.add(q_pass)

            if srcpad.link(q_pass.get_static_pad("sink")) != Gst.PadLinkReturn.OK:
                sys.stderr.write(f"Failed to link source -> pass queue for stream {i}\n")
                return None

            branch_out_pad = q_pass.get_static_pad("src")

        if not branch_out_pad:
            sys.stderr.write(f"Failed to create branch for stream {i}\n")
            return None

        main_sinkpad = main_streammux.request_pad_simple(f"sink_{i}")
        if not main_sinkpad:
            sys.stderr.write(f"Failed to request main mux sink_{i}\n")
            return None

        if branch_out_pad.link(main_sinkpad) != Gst.PadLinkReturn.OK:
            sys.stderr.write(f"Failed to link branch -> main mux sink_{i}\n")
            return None

    tracker = Gst.ElementFactory.make("nvtracker", "tracker")
    if not tracker:
        sys.stderr.write("Unable to create tracker\n")
        return None

    tracker_config = configparser.ConfigParser()
    tracker_config.read(config.TRACKER_CONFIG_FILE)

    if "tracker" in tracker_config:
        for key, value in tracker_config["tracker"].items():
            if key == "tracker-width":
                tracker.set_property("tracker-width", int(value))
            elif key == "tracker-height":
                tracker.set_property("tracker-height", int(value))
            elif key == "gpu-id":
                tracker.set_property("gpu_id", int(value))
            else:
                tracker.set_property(key, value)

    tiler = Gst.ElementFactory.make("nvmultistreamtiler", "nvtiler")
    nvvidconv = Gst.ElementFactory.make("nvvideoconvert", "convertor")
    nvosd = Gst.ElementFactory.make("nvdsosd", "onscreendisplay")

    if platform_info.is_platform_aarch64() or platform_info.is_integrated_gpu():
        sink = Gst.ElementFactory.make("nv3dsink", "nv3d-sink")
    else:
        sink = Gst.ElementFactory.make("nveglglessink", "nvvideo-renderer")

    if not tiler or not nvvidconv or not nvosd or not sink:
        sys.stderr.write("Unable to create display elements\n")
        return None

    tiler_columns = 3
    tiler_rows = int(math.ceil(number_sources / tiler_columns))

    tiler.set_property("rows", tiler_rows)
    tiler.set_property("columns", tiler_columns)
    tiler.set_property("width", config.TILED_OUTPUT_WIDTH)
    tiler.set_property("height", config.TILED_OUTPUT_HEIGHT)

    nvosd.set_property("process-mode", config.OSD_PROCESS_MODE)
    nvosd.set_property("display-text", config.OSD_DISPLAY_TEXT)

    sink.set_property("qos", 0)
    sink.set_property("sync", 0 if is_live else 1)

    for element in [tracker, tiler, nvvidconv, nvosd, sink]:
        pipeline.add(element)

    if not main_streammux.link(tracker):
        sys.stderr.write("Failed to link main_streammux -> tracker\n")
        return None

    if not tracker.link(tiler):
        sys.stderr.write("Failed to link tracker -> tiler\n")
        return None

    if not tiler.link(nvvidconv):
        sys.stderr.write("Failed to link tiler -> nvvidconv\n")
        return None

    if not nvvidconv.link(nvosd):
        sys.stderr.write("Failed to link nvvidconv -> nvosd\n")
        return None

    if not nvosd.link(sink):
        sys.stderr.write("Failed to link nvosd -> sink\n")
        return None

    return pipeline
