# System Design

This document details the software design choices, memory management strategies, and configuration schemas driving the Parallel RTSP application.

## Design Philosophy

The primary design goal is maximum throughput with minimal CPU-GPU memory latency. To achieve this, the system strictly adheres to the DeepStream paradigm: data, once decoded into NVIDIA Memory Management (NVMM) buffers, must not leave NVMM until rendering or network transmission.

### 1. Data Flow & Memory Management

Standard OpenCV/CPU-based pipelines suffer from massive bottlenecks when copying highly-dense frame data from the GPU buffer to system RAM for inference and back.

*   **Zero-Copy Design:** This system uses `GstBuffer` passing. The actual image payload resides in discrete VRAM. The elements in the pipeline are only passing pointers (metadata) between plugins.
*   **Decoupled Inference:** By placing `nvinfer` elements on isolated branches before the main synchronization point (`main-stream-muxer`), inferencing is not bottlenecked by the slowest stream.

### 2. Multi-Threading & Concurrency

GStreamer handles threading innately through queues and pads.

*   **Branch Queues:** You will note the use of `queue` elements (e.g., `sub_q1_{index}`, `sub_q2_{index}`) surrounding the `nvstreammux` and `nvstreamdemux` blocks inside `create_inference_branch`. These queues act as thread boundaries. They decouple the decoding thread from the inference thread, allowing the hardware decoder (NVDEC) to continue churning frames asynchronously while TensorRT computes inference.
*   **Batched Push Timeout:** The `batched-push-timeout` property on the stream muxers ensures the pipeline does not stall indefinitely if a camera feed drops. It acts as a concurrency watchdog, pushing a partial/empty batch if the time threshold is breached.

### 3. Modularity and Configuration

The system is designed for extensibility. Instead of hardcoding inference logic into the pipeline builder, the application relies heavily on NVIDIA's text-based configuration schema.

#### Configuration Files

The behavior of the heavy plugins (`nvinfer` and `nvtracker`) is dictated entirely by external `.txt` config files.

*   `config_infer_primary_peoplenet.txt`: Defines the TensorRT engine parameters, threshold confidences, and network dimensions for Streams 0 and 1.
*   `config_infer_primary_trafficcamnet.txt`: Holds similar data optimized for vehicle tracking for Streams 2, 3, and 4.
*   `dsnvanalytics_tracker_config.txt`: Defines the parameters for the low-level NvDCF (NVIDIA Data Center Filter) or IOU tracker.

### 4. Hardware Awareness

The initialization logic contains a `PlatformInfo` class designed to query the underlying architecture.
The pipeline adapts its chosen display sink (`nveglglessink` vs `nv3dsink`) based on whether the host is an x86 discrete GPU or an ARM-based Jetson SoC. This prevents cryptic OpenGL errors on headless or embedded setups.
