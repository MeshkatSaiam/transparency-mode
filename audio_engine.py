"""
Audio Engine for Transparency Mode.
Handles real-time, ultra-low-latency, full-duplex audio passthrough from microphone to headphones
using sounddevice with native WASAPI, numpy, and scipy.signal for bandpass filtering (Voice Boost).
Features:
- Expanded Gain control (up to 400% / +12dB boost)
- Advanced Voice Boost DSP (180Hz HPF + 3kHz +8dB Presence Peak EQ + 6.5kHz Low-Pass)
- Ultra-low latency buffer sizes (32, 64, 128, 256 frames)
- Left / Right stereo balance control
- Soft saturation limiter (tanh) to prevent harsh digital clipping
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
        elif "mme" in api.lower():
            return "MME"
        elif "wdm-ks" in api.lower():
            return "WDM-KS"
        return api

    @property
    def display_name(self) -> str:
        badge = "WASAPI (Lowest Latency)" if self.is_wasapi else self.short_api
        return f"[{badge}] {self.name} (#{self.index})"

    def __repr__(self) -> str:
        return f"<AudioDevice {self.display_name}>"


class AudioEngine:
    """
    Real-time full-duplex audio passthrough engine with Left/Right balance control.
    Uses native WASAPI streaming for immediate, zero-lag passthrough.
    """
    def __init__(self, on_status_changed: Optional[Callable[[bool, str], None]] = None):
        self._is_running = False
        self._stream: Optional[sd.Stream] = None
        self._lock = threading.Lock()
        self.on_status_changed = on_status_changed

        # User controls
        self._gain: float = 1.0       # 0.0 to 4.0 (0% to 400%)
        self._balance: float = 0.0    # -1.0 (Full Left) to +1.0 (Full Right), 0.0 = Center
        self._voice_boost: bool = False
        self._blocksize: int = 64      # frames: 32, 64, 128, 256
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
        self._gain = max(0.0, min(float(value), 4.5))

    @property
    def balance(self) -> float:
        return self._balance

    @balance.setter
    def balance(self, value: float):
        self._balance = max(-1.0, min(1.0, float(value)))

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
        """Single-buffer block latency in milliseconds."""
        if self._samplerate > 0 and self._blocksize > 0:
            return (self._blocksize / self._samplerate) * 1000.0
        return 0.0

    @property
    def actual_latency_ms(self) -> Tuple[float, float, float]:
        """
        Returns (in_latency_ms, out_latency_ms, total_roundtrip_ms) reported by driver.
        """
        if self._stream and self._is_running:
            try:
                lat = self._stream.latency
                if isinstance(lat, (tuple, list)) and len(lat) >= 2:
                    in_ms = float(lat[0]) * 1000.0
                    out_ms = float(lat[1]) * 1000.0
                    return (in_ms, out_ms, in_ms + out_ms)
            except Exception:
                pass
        b_ms = self.estimated_latency_ms
        return (b_ms, b_ms, b_ms * 2.0)

    @staticmethod
    def get_devices() -> Tuple[List[AudioDevice], List[AudioDevice]]:
        """
        Enumerate all audio devices prioritizing WASAPI devices for lowest latency.
        Excludes virtual wrapper devices (FlexASIO) that cause buffer bloat.
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

            # Filter out FlexASIO / virtual wrapper loops
            if "flexasio" in name.lower():
                continue

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

        # Sort priority:
        # 0: WASAPI
        # 1: DirectSound
        # 2: MME
        # 3: Others
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
        Design an advanced 3-stage Voice Boost SOS filter:
        1. 2nd-order High-Pass filter at 180 Hz (cuts desk rumbles, HVAC drone).
        2. 2nd-order Peaking EQ at 3000 Hz (+8 dB boost) to restore natural ear canal presence resonance.
        3. 2nd-order Low-Pass filter at 6500 Hz (cuts sharp electrical coil whine & fan hiss).
        """
        try:
            # Stage 1: High-pass at 180 Hz
            hp_sos = signal.butter(2, 180.0, btype='highpass', fs=samplerate, output='sos')

            # Stage 2: Peaking EQ at 3000 Hz (+8 dB)
            presence_db = 8.0
            A = 10.0 ** (presence_db / 40.0)
            w0 = 2.0 * np.pi * 3000.0 / samplerate
            alpha = np.sin(w0) / (2.0 * 1.2)  # Q = 1.2
            b0 = 1.0 + alpha * A
            b1 = -2.0 * np.cos(w0)
            b2 = 1.0 - alpha * A
            a0 = 1.0 + alpha / A
            a1 = -2.0 * np.cos(w0)
            a2 = 1.0 - alpha / A
            peak_sos = np.array([[b0/a0, b1/a0, b2/a0, 1.0, a1/a0, a2/a0]], dtype=np.float32)

            # Stage 3: Low-pass roll-off at 6500 Hz
            lp_sos = signal.butter(2, min(6500.0, (samplerate / 2.0) - 200.0), btype='lowpass', fs=samplerate, output='sos')

            self._filter_sos = np.vstack([hp_sos, peak_sos, lp_sos])
            base_zi = signal.sosfilt_zi(self._filter_sos)
            self._filter_zi = np.repeat(base_zi[:, :, np.newaxis], channels, axis=2).astype(np.float32)
            self._filter_channels = channels
        except Exception as e:
            self._filter_sos = None
            self._filter_zi = None
            self._filter_channels = 0
            print(f"[AudioEngine] Failed to initialize Voice Boost filter: {e}")

    def _determine_samplerate(self, in_dev_idx: int, out_dev_idx: int, in_ch: int, out_ch: int) -> int:
        """Find mutually supported sample rate, prioritizing native 48kHz."""
        candidate_rates = [48000, 44100, 96000]
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
        Routes microphone indata -> headphone outdata with Voice Boost EQ, Gain, L/R balance, and Soft Limiter.
        """
        if status:
            if status.input_overflow or status.output_overflow:
                self.overflow_count += 1
            if status.input_underflow or status.output_underflow:
                self.underflow_count += 1

        data = indata.astype(np.float32, copy=False)
        in_channels = data.shape[1]
        out_channels = outdata.shape[1]

        # 1. Voice Boost (Vocal Presence Peaking EQ + Rumble High-Pass)
        if self._voice_boost and self._filter_sos is not None and self._filter_zi is not None:
            if in_channels == self._filter_channels:
                try:
                    data, self._filter_zi = signal.sosfilt(
                        self._filter_sos, data, axis=0, zi=self._filter_zi
                    )
                except Exception:
                    pass

        # 2. Passthrough Gain (up to 400% / +12dB)
        gain = self._gain
        if gain != 1.0:
            data = data * gain

        # 3. Soft Limiter (Smooth tanh saturation when signal exceeds +/- 0.90)
        # Prevents loud claps or coughs from causing ear fatigue while keeping quiet speech loud
        max_abs = np.max(np.abs(data)) if data.size > 0 else 0.0
        if max_abs > 0.90:
            data = np.tanh(data * 0.95)

        # 4. Measure levels for VU meter
        self.current_peak_level = float(min(1.0, max_abs))
        self.current_rms_level = float(min(1.0, np.sqrt(np.mean(data**2)) * 2.5)) if data.size > 0 else 0.0

        # 5. Channel Mapping: adapt input channels to output channels
        if in_channels == out_channels:
            outdata[:] = data
        elif in_channels == 1 and out_channels == 2:
            outdata[:, 0] = data[:, 0]
            outdata[:, 1] = data[:, 0]
        elif in_channels >= 2 and out_channels == 1:
            outdata[:, 0] = np.mean(data, axis=1)
        else:
            min_ch = min(in_channels, out_channels)
            outdata[:, :min_ch] = data[:, :min_ch]
            if out_channels > min_ch:
                outdata[:, min_ch:] = 0.0

        # 6. Left / Right Stereo Balance
        if out_channels >= 2 and self._balance != 0.0:
            bal = self._balance
            if bal < 0.0:
                l_factor = 1.0
                r_factor = 1.0 + bal
            else:
                l_factor = 1.0 - bal
                r_factor = 1.0

            outdata[:, 0] *= l_factor
            outdata[:, 1] *= r_factor

    def start(self, input_device: AudioDevice, output_device: AudioDevice, 
              blocksize: Optional[int] = None) -> bool:
        """
        Start the audio passthrough stream using native WASAPI direct hardware streaming.
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

            self._setup_bandpass_filter(self._samplerate, in_ch)

            try:
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
