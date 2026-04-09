# Parallel RTSP Video Analytics Pipeline

This project implements a high-performance, parallelized video analytics pipeline using the **NVIDIA DeepStream SDK** and **GStreamer**. It is designed to ingest multiple RTSP and/or local V4L2 video streams simultaneously, apply varying deep learning inference models based on the stream source, track objects, and display a tiled output matrix in real-time.

## Key Features

*   **Multi-Stream Ingestion:** Supports simultaneous decoding and processing of local USB cameras (v4l2) and remote IP cameras (RTSP).
*   **Dynamic Inference Branching:** Applies specific AI models to specific streams rather than a one-size-fits-all approach:
    *   **Streams 0 & 1:** Route through NVIDIA **PeopleNet** for human detection.
    *   **Streams 2, 3 & 4:** Route through NVIDIA **TrafficCamNet** for vehicle and traffic analytics.
    *   **Subsequent Streams:** Configured as pure pass-through for monitoring without inference overhead.
*   **Hardware Acceleration:** End-to-end GPU acceleration leveraging NVDEC for decoding, TensorRT for inference, NVENC (optional) for encoding, and EGL for rendering.
*   **Advanced Tracking:** Integrates `nvtracker` to assign unique IDs to detected objects across frames.
*   **Tiled Visualization:** Automatically scales and tiles input streams into a cohesive grid utilizing `nvmultistreamtiler`.

## Prerequisites

To run this application, your system must meet the following hardware and software requirements:

*   **Hardware:** NVIDIA Jetson device (Orin/Xavier/Nano) OR an x86_64 host with a discrete NVIDIA GPU.
*   **OS:** Ubuntu 20.04 or 22.04
*   **DeepStream SDK:** Version 6.0 or higher installed.
*   **Python:** Python 3.8+ with Gst-Python bindings.

## Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/Parthiban1805/deepstream-rtsp-parallel.git
    cd deepstream-rtsp-parallel
    ```

2.  **Install dependencies:**
    Ensure you have the necessary system packages for GStreamer and Python installed, then install Python requirements:
    ```bash
    pip install -r requirements.txt
    ```

## Usage

The application is executed via the command-line interface. You must provide the URIs for the video streams as positional arguments.

```bash
python3 parallel_rtsp/main.py <uri1> [uri2] ... [uriN]
```

### Examples

**Running with mixed local and RTSP streams:**
```bash
python3 parallel_rtsp/main.py v4l2:///dev/video0 rtsp://user:pass@192.168.1.100:554/stream1 rtsp://10.0.0.5/live
```
*Note: In the above example, `/dev/video0` and the first RTSP stream will be processed by PeopleNet, while the second RTSP stream will be processed by TrafficCamNet.*
