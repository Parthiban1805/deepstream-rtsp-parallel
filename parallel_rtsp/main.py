# main.py

#!/usr/bin/env python3

import sys
sys.path.append('./common')
import gi
gi.require_version('Gst', '1.0')
from gi.repository import GLib, Gst

from common.bus_call import bus_call
from common.FPS import PERF_DATA

import pipeline_builder

def main(args):
    if len(args) < 2:
        sys.stderr.write(f"Usage: {args[0]} <uri1> [uri2] ... [uriN]\n")
        sys.exit(1)

    number_sources = len(args) - 1
    perf_data = PERF_DATA(number_sources)

    Gst.init(None)

    print("Creating Pipeline \n")
    pipeline = pipeline_builder.build_pipeline(number_sources, args)
    if pipeline is None:
        sys.stderr.write("Failed to build the pipeline\n")
        return

    loop = GLib.MainLoop()
    bus = pipeline.get_bus()
    bus.add_signal_watch()
    bus.connect("message", bus_call, loop)

    # Add a callback to print FPS periodically
    GLib.timeout_add(5000, perf_data.perf_print_callback)

    print("Now playing...")
    for i, source in enumerate(args[1:], 1):
        print(f"{i}: {source}")
    
    print("Starting pipeline \n")
    pipeline.set_state(Gst.State.PLAYING)

    try:
        loop.run()
    except KeyboardInterrupt:
        print("User interrupted, exiting.")
    finally:
        print("Exiting app\n")
        pipeline.set_state(Gst.State.NULL)

if __name__ == '__main__':
    sys.exit(main(sys.argv))