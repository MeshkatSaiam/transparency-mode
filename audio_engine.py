"""
Audio Engine for Transparency Mode.
Handles real-time, low-latency, full-duplex audio passthrough from microphone to headphones
using sounddevice, numpy, and scipy.signal for bandpass filtering (Voice Boost).
"""

import threading
import sounddevice as sd
import numpy as np
from scipy import signal
from typing import Dict, List, Tuple, Optional, Callable


class AudioDevice:
    """Represents an audio input or output device."""
    def __init__(self, index: int, name: str, hostapi_name: str, 
                 max_input_channels: int, max_output_channels: int, 
                 default_samplerate: float):
        self.index = index
        self.name = name
        self.hostapi_name = hostapi_name
        self.max_input_channels = max_input_channels
        self.max_output_channels = max_output_channels
        self.default_samplerate = default_samplerate

    @property
    def is_wasapi(self) -> bool:
        return "wasapi" in self.hostapi_name.lower()

    @property
    def short_api(self) -> str:
        api = self.hostapi_name
        if "wasapi" in api.lower():
            return "WASAPI"
        elif "directsound" in api.lower():
            return "DirectSound"
        elif "wdm-ks" in api.lower():
            return "WDM-KS"
        elif "mme" in api.lower():
            return "MME"
        return api

    @property
    def display_name(self) -> str:
        badge = "WASAPI (Low Latency)" if self.is_wasapi else self.short_api
        return f"[{badge}] {self.name} (#{self.index})"

    def __repr__(self) -> str:
        return f"<AudioDevice {self.display_name}>"


class AudioEngine:
    """
    Real-time full-duplex audio passthrough engine.
    """
    def __init__(self, on_status_changed: Optional[Callable[[bool, str], None]] = None):
        self._is_running = False
        self._stream: Optional[sd.Stream] = None
        self._lock = threading.Lock()
        self.on_status_changed = on_status_changed

        # User controls
        self._gain: float = 1.0  # 0.0 to 2.0 (0% to 200%)
        self._voice_boost: bool = False
        self._blocksize: int = 256  # frames: 128, 256, 512
        self._samplerate: int = 48000

        # Filter state
        self._filter_sos: Optional[np.ndarray] = None
        self._filter_zi: Optional[np.ndarray] = None
        self._filter_channels: int = 0

        # Selected devices
        self.selected_input: Optional[AudioDevice] = None
        self.selected_output: Optional[AudioDevice] = None

        # Level metering (0.0 to 1.0)
        self.current_peak_level: float = 0.0
        self.current_rms_level: float = 0.0

        # Diagnostics
        self.last_error: str = ""
        self.underflow_count: int = 0
        self.overflow_count: int = 0

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def gain(self) -> float:
        return self._gain

    @gain.setter
    def gain(self, value: float):
        self._gain = max(0.0, min(float(value), 2.5))

    @property
    def voice_boost(self) -> bool:
        return self._voice_boost

    @voice_boost.setter
    def voice_boost(self, value: bool):
        self._voice_boost = bool(value)

    @property
    def blocksize(self) -> int:
        return self._blocksize

    @blocksize.setter
    def blocksize(self, value: int):
        self._blocksize = int(value)

    @property
    def samplerate(self) -> int:
        return self._samplerate

    @property
    def estimated_latency_ms(self) -> float:
        """Estimated one-way buffer latency in milliseconds."""
        if self._samplerate > 0 and self._blocksize > 0:
            return (self._blocksize / self._samplerate) * 1000.0
        return 0.0

    @staticmethod
    def get_devices() -> Tuple[List[AudioDevice], List[AudioDevice]]:
        """
        Enumerate all audio devices and sort them with WASAPI devices prioritized.
        Returns: (input_devices, output_devices)
        """
        try:
            host_apis = {i: h['name'] for i, h in enumerate(sd.query_hostapis())}
            raw_devices = sd.query_devices()
        except Exception:
            return [], []

        input_devices: List[AudioDevice] = []
        output_devices: List[AudioDevice] = []

        for idx, d in enumerate(raw_devices):
            api_name = host_apis.get(d.get('hostapi', -1), 'Unknown')
            name = d.get('name', f'Device #{idx}')
            in_ch = d.get('max_input_channels', 0)
            out_ch = d.get('max_output_channels', 0)
            rate = d.get('default_samplerate', 48000.0)

            device_obj = AudioDevice(
                index=idx,
                name=name,
                hostapi_name=api_name,
                max_input_channels=in_ch,
                max_output_channels=out_ch,
                default_samplerate=rate
            )

            if in_ch > 0:
                input_devices.append(device_obj)
            if out_ch > 0:
                output_devices.append(device_obj)

        # Sort priority: WASAPI first (0), DirectSound (1), MME (2), others (3)
        def sort_key(dev: AudioDevice):
            api_lower = dev.hostapi_name.lower()
            if "wasapi" in api_lower:
                priority = 0
            elif "directsound" in api_lower:
                priority = 1
            elif "mme" in api_lower:
                priority = 2
            else:
                priority = 3
            return (priority, dev.name.lower())

        input_devices.sort(key=sort_key)
        output_devices.sort(key=sort_key)

        return input_devices, output_devices

    def _setup_bandpass_filter(self, samplerate: int, channels: int):
        """
        Design a 2nd-order Butterworth bandpass filter (300Hz - 3400Hz)
        using Second-Order Sections (SOS) for numerical stability and zero clicks.
        """
        lowcut = 300.0
        highcut = min(3400.0, (samplerate / 2.0) - 200.0)  # Must be below Nyquist
        
        try:
            self._filter_sos = signal.butter(
                N=2,
                Wn=[lowcut, highcut],
                btype='bandpass',
                fs=samplerate,
                output='sos'
            )
            base_zi = signal.sosfilt_zi(self._filter_sos)  # shape: (n_sections, 2)
            # Expand zi for multi-channel: (n_sections, 2, channels)
            self._filter_zi = np.repeat(base_zi[:, :, np.newaxis], channels, axis=2).astype(np.float32)
            self._filter_channels = channels
        except Exception as e:
            self._filter_sos = None
            self._filter_zi = None
            self._filter_channels = 0
            print(f"[AudioEngine] Failed to initialize bandpass filter: {e}")

    def _determine_samplerate(self, in_dev_idx: int, out_dev_idx: int, in_ch: int, out_ch: int) -> int:
        """Find a mutually supported sample rate, prioritizing WASAPI default 48kHz."""
        candidate_rates = [48000, 44100, 96000, 88200]
        
        # Check defaults first
        try:
            out_info = sd.query_devices(out_dev_idx)
            in_info = sd.query_devices(in_dev_idx)
            suggested = [int(out_info.get('default_samplerate', 48000)),
                         int(in_info.get('default_samplerate', 48000))]
        except Exception:
            suggested = []

        all_candidates = []
        for r in suggested + candidate_rates:
            if r not in all_candidates and r > 0:
                all_candidates.append(r)

        for rate in all_candidates:
            try:
                sd.check_input_settings(device=in_dev_idx, samplerate=rate, channels=in_ch, dtype='float32')
                sd.check_output_settings(device=out_dev_idx, samplerate=rate, channels=out_ch, dtype='float32')
                return rate
            except Exception:
                continue

        return 48000

    def _audio_callback(self, indata: np.ndarray, outdata: np.ndarray, 
                        frames: int, time_info, status):
        """
        High-performance real-time duplex audio callback.
        Routes microphone indata -> headphone outdata with DSP processing.
        """
        if status:
            if status.input_overflow or status.output_overflow:
                self.overflow_count += 1
            if status.input_underflow or status.output_underflow:
                self.underflow_count += 1

        # Work on a copy or directly on buffer
        data = indata.astype(np.float32, copy=False)
        in_channels = data.shape[1]
        out_channels = outdata.shape[1]

        # 1. Voice Boost (Speech Band-pass filter 300Hz - 3400Hz)
        if self._voice_boost and self._filter_sos is not None and self._filter_zi is not None:
            if in_channels == self._filter_channels:
                try:
                    data, self._filter_zi = signal.sosfilt(
                        self._filter_sos, data, axis=0, zi=self._filter_zi
                    )
                except Exception:
                    pass

        # 2. Passthrough Gain
        gain = self._gain
        if gain != 1.0:
            data = data * gain

        # 3. Soft Limiter (Smooth saturation using tanh when signal exceeds +/- 0.95)
        # Prevents harsh digital clipping pops while maintaining transparency
        max_abs = np.max(np.abs(data)) if data.size > 0 else 0.0
        if max_abs > 0.95:
            data = np.tanh(data)

        # 4. Measure levels for VU meter
        self.current_peak_level = float(min(1.0, max_abs))
        self.current_rms_level = float(min(1.0, np.sqrt(np.mean(data**2)) * 2.5)) if data.size > 0 else 0.0

        # 5. Channel Mapping: adapt input channels to output channels
        if in_channels == out_channels:
            outdata[:] = data
        elif in_channels == 1 and out_channels == 2:
            # Mono to Stereo
            outdata[:, 0] = data[:, 0]
            outdata[:, 1] = data[:, 0]
        elif in_channels >= 2 and out_channels == 1:
            # Downmix Stereo/Multi to Mono
            outdata[:, 0] = np.mean(data, axis=1)
        else:
            # General fallback: replicate or truncate
            min_ch = min(in_channels, out_channels)
            outdata[:, :min_ch] = data[:, :min_ch]
            if out_channels > min_ch:
                outdata[:, min_ch:] = 0.0

    def start(self, input_device: AudioDevice, output_device: AudioDevice, 
              blocksize: Optional[int] = None) -> bool:
        """
        Start the audio passthrough stream.
        """
        with self._lock:
            if self._is_running:
                self.stop()

            if blocksize is not None:
                self._blocksize = blocksize

            self.selected_input = input_device
            self.selected_output = output_device

            in_ch = min(2, max(1, input_device.max_input_channels))
            out_ch = min(2, max(1, output_device.max_output_channels))

            self._samplerate = self._determine_samplerate(
                input_device.index, output_device.index, in_ch, out_ch
            )

            # Setup filter for this samplerate and channel configuration
            self._setup_bandpass_filter(self._samplerate, in_ch)

            try:
                # Open real-time full-duplex stream
                self._stream = sd.Stream(
                    device=(input_device.index, output_device.index),
                    samplerate=self._samplerate,
                    blocksize=self._blocksize,
                    channels=(in_ch, out_ch),
                    dtype='float32',
                    latency='low',
                    callback=self._audio_callback
                )
                self._stream.start()
                self._is_running = True
                self.last_error = ""

                if self.on_status_changed:
                    self.on_status_changed(True, "Running")
                return True

            except Exception as e:
                self._is_running = False
                self.last_error = str(e)
                if self.on_status_changed:
                    self.on_status_changed(False, f"Error: {e}")
                return False

    def stop(self):
        """Stop the audio stream cleanly."""
        with self._lock:
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                finally:
                    self._stream = None

            self._is_running = False
            self.current_peak_level = 0.0
            self.current_rms_level = 0.0

            if self.on_status_changed:
                self.on_status_changed(False, "Stopped")

    def toggle(self, input_device: Optional[AudioDevice] = None, 
               output_device: Optional[AudioDevice] = None) -> bool:
        """Toggle audio passthrough on/off."""
        if self._is_running:
            self.stop()
            return False
        else:
            in_dev = input_device or self.selected_input
            out_dev = output_device or self.selected_output
            if in_dev and out_dev:
                return self.start(in_dev, out_dev)
            return False
