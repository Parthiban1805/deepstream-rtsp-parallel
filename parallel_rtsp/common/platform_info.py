################################################################################
# SPDX-FileCopyrightText: Copyright (c) 2024 NVIDIA CORPORATION & AFFILIATES.
# SPDX-License-Identifier: Apache-2.0
################################################################################

import platform
from threading import Lock

guard_platform_info = Lock()

class PlatformInfo:
    def __init__(self):
        self.is_wsl_system = False
        self.wsl_verified = False
        self.is_integrated_gpu_system = False
        self.is_integrated_gpu_verified = False
        self.is_aarch64_platform = False
        self.is_aarch64_verified = False

    def is_wsl(self):
        with guard_platform_info:
            if not self.wsl_verified:
                try:
                    with open("/proc/version", "r") as version_file:
                        version_info = version_file.readline().lower()
                        if "microsoft" in version_info:
                            self.is_wsl_system = True
                        self.wsl_verified = True
                except Exception as e:
                    print(f"ERROR: Unable to open /proc/version: {e}")
        return self.is_wsl_system

    def is_integrated_gpu(self):
        # Always return False for discrete GPU on x86_64 (like RTX 3060)
        return False

    def is_platform_aarch64(self):
        with guard_platform_info:
            if not self.is_aarch64_verified:
                self.is_aarch64_platform = platform.uname()[4] == 'aarch64'
                self.is_aarch64_verified = True
        return self.is_aarch64_platform
