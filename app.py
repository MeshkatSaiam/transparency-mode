"""
Transparency Mode - Windows Desktop Application
Built with CustomTkinter, SoundDevice, NumPy, Scipy, and Keyboard.

Allows seamless audio passthrough from microphone to headphones with:
- Native WASAPI direct hardware streaming (minimal 0.7ms - 1.3ms buffers)
- Expanded Passthrough Gain slider (0% to 400% / +12 dB boost)
- Quick-boost presets for closed-back over-ear headphone compensation
- Advanced Voice Boost DSP (180Hz HPF + 3kHz +8dB Vocal Presence Peaking EQ)
- Left / Right Stereo Balance slider (-100% to +100%)
- Global hotkey (Ctrl + Alt + T)
"""

import sys
import threading
from typing import Dict, Optional, List, Tuple
import customtkinter as ctk
import keyboard
import numpy as np

from audio_engine import AudioEngine, AudioDevice

# Theme and style
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class TransparencyApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Transparency Mode")
        self.geometry("560x800")
        self.minsize(520, 740)
        self.resizable(True, True)

        # Initialize audio engine
        self.audio_engine = AudioEngine(on_status_changed=self._on_engine_status_changed)

        # Device mapping caches
        self.input_device_map: Dict[str, AudioDevice] = {}
        self.output_device_map: Dict[str, AudioDevice] = {}

        # Hotkey setup state
        self.hotkey_registered = False

        # Build UI
        self._create_widgets()

        # Populate devices
        self.refresh_devices()

        # Register global hotkey
        self._setup_global_hotkey()

        # Start UI update loop for VU meter and latency diagnostics
        self._start_meter_poll()

        # Handle window close
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def _create_widgets(self):
        self.grid_columnconfigure(0, weight=1)

        # ----------------- 1. HEADER SECTION -----------------
        header_frame = ctk.CTkFrame(self, corner_radius=12, fg_color="#1e293b")
        header_frame.pack(fill="x", padx=16, pady=(14, 8))

        title_box = ctk.CTkFrame(header_frame, fg_color="transparent")
        title_box.pack(fill="x", padx=16, pady=12)

        title_lbl = ctk.CTkLabel(
            title_box,
            text="🎧 Transparency Mode",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color="#f8fafc"
        )
        title_lbl.pack(anchor="w")

        subtitle_lbl = ctk.CTkLabel(
            title_box,
            text="Real-time ambient microphone passthrough for over-ear headphones",
            font=ctk.CTkFont(size=12),
            text_color="#94a3b8"
        )
        subtitle_lbl.pack(anchor="w", pady=(2, 0))

        # Status & Latency Badges
        badge_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        badge_frame.pack(fill="x", padx=16, pady=(0, 10))

        self.status_badge = ctk.CTkLabel(
            badge_frame,
            text="● STANDBY",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#94a3b8",
            fg_color="#0f172a",
            corner_radius=6,
            padx=10,
            pady=4
        )
        self.status_badge.pack(side="left")

        self.latency_badge = ctk.CTkLabel(
            badge_frame,
            text="Buffer: 64 frames (1.3 ms)",
            font=ctk.CTkFont(size=11),
            text_color="#38bdf8",
            fg_color="#0f172a",
            corner_radius=6,
            padx=10,
            pady=4
        )
        self.latency_badge.pack(side="right")

        # ----------------- 2. GIANT TOGGLE BUTTON -----------------
        self.toggle_btn = ctk.CTkButton(
            self,
            text="🔊  ACTIVATE TRANSPARENCY MODE",
            font=ctk.CTkFont(size=15, weight="bold"),
            height=54,
            corner_radius=12,
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            text_color="#ffffff",
            command=self.toggle_transparency
        )
        self.toggle_btn.pack(fill="x", padx=16, pady=(2, 6))

        # Hotkey indicator under button
        hotkey_hint = ctk.CTkLabel(
            self,
            text="Quick Toggle Hotkey:  Ctrl + Alt + T  (works globally across all apps)",
            font=ctk.CTkFont(size=11),
            text_color="#64748b"
        )
        hotkey_hint.pack(pady=(0, 8))

        # ----------------- 3. DEVICE SELECTION CARD -----------------
        device_card = ctk.CTkFrame(self, corner_radius=12, fg_color="#1e293b")
        device_card.pack(fill="x", padx=16, pady=(0, 8))

        card_title_row = ctk.CTkFrame(device_card, fg_color="transparent")
        card_title_row.pack(fill="x", padx=14, pady=(10, 4))

        device_title = ctk.CTkLabel(
            card_title_row,
            text="Audio Endpoints  (WASAPI Direct Low-Latency)",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#e2e8f0"
        )
        device_title.pack(side="left")

        refresh_btn = ctk.CTkButton(
            card_title_row,
            text="🔄 Refresh",
            width=80,
            height=24,
            font=ctk.CTkFont(size=11),
            fg_color="#334155",
            hover_color="#475569",
            command=self.refresh_devices
        )
        refresh_btn.pack(side="right")

        # Input Microphone Menu
        in_row = ctk.CTkFrame(device_card, fg_color="transparent")
        in_row.pack(fill="x", padx=14, pady=3)

        in_label = ctk.CTkLabel(
            in_row,
            text="🎤 Input Mic:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#94a3b8",
            width=110,
            anchor="w"
        )
        in_label.pack(side="left")

        self.input_dropdown = ctk.CTkOptionMenu(
            in_row,
            values=["Searching devices..."],
            command=self._on_device_changed,
            height=30,
            font=ctk.CTkFont(size=11),
            dropdown_font=ctk.CTkFont(size=11),
            fg_color="#0f172a",
            button_color="#334155",
            button_hover_color="#475569"
        )
        self.input_dropdown.pack(side="left", fill="x", expand=True)

        # Output Headphones Menu
        out_row = ctk.CTkFrame(device_card, fg_color="transparent")
        out_row.pack(fill="x", padx=14, pady=(3, 10))

        out_label = ctk.CTkLabel(
            out_row,
            text="🎧 Output Audio:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#94a3b8",
            width=110,
            anchor="w"
        )
        out_label.pack(side="left")

        self.output_dropdown = ctk.CTkOptionMenu(
            out_row,
            values=["Searching devices..."],
            command=self._on_device_changed,
            height=30,
            font=ctk.CTkFont(size=11),
            dropdown_font=ctk.CTkFont(size=11),
            fg_color="#0f172a",
            button_color="#334155",
            button_hover_color="#475569"
        )
        self.output_dropdown.pack(side="left", fill="x", expand=True)

        # ----------------- 4. AUDIO CONTROLS CARD -----------------
        controls_card = ctk.CTkFrame(self, corner_radius=12, fg_color="#1e293b")
        controls_card.pack(fill="x", padx=16, pady=(0, 8))

        # A) Passthrough Gain Slider (0% to 400%)
        gain_header = ctk.CTkFrame(controls_card, fg_color="transparent")
        gain_header.pack(fill="x", padx=14, pady=(10, 2))

        gain_title = ctk.CTkLabel(
            gain_header,
            text="Passthrough Volume Gain (Up to +12 dB)",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#e2e8f0"
        )
        gain_title.pack(side="left")

        self.gain_val_lbl = ctk.CTkLabel(
            gain_header,
            text="100% (Unity)",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#38bdf8"
        )
        self.gain_val_lbl.pack(side="right")

        gain_slider_row = ctk.CTkFrame(controls_card, fg_color="transparent")
        gain_slider_row.pack(fill="x", padx=14, pady=(2, 4))

        self.gain_slider = ctk.CTkSlider(
            gain_slider_row,
            from_=0.0,
            to=4.0,
            number_of_steps=80,
            command=self._on_gain_changed,
            progress_color="#0284c7",
            button_color="#38bdf8",
            button_hover_color="#7dd3fc"
        )
        self.gain_slider.set(1.0)
        self.gain_slider.pack(side="left", fill="x", expand=True, padx=(0, 10))

        # Preset buttons for fast gain selection
        presets_box = ctk.CTkFrame(gain_slider_row, fg_color="transparent")
        presets_box.pack(side="right")

        ctk.CTkButton(
            presets_box,
            text="100%",
            width=50,
            height=24,
            font=ctk.CTkFont(size=10),
            fg_color="#334155",
            hover_color="#475569",
            command=lambda: self._set_gain_preset(1.0)
        ).pack(side="left", padx=2)

        ctk.CTkButton(
            presets_box,
            text="200%",
            width=50,
            height=24,
            font=ctk.CTkFont(size=10),
            fg_color="#334155",
            hover_color="#475569",
            command=lambda: self._set_gain_preset(2.0)
        ).pack(side="left", padx=2)

        ctk.CTkButton(
            presets_box,
            text="🚀 300%",
            width=62,
            height=24,
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color="#0284c7",
            hover_color="#0369a1",
            command=lambda: self._set_gain_preset(3.0)
        ).pack(side="left", padx=2)

        gain_scale_lbls = ctk.CTkFrame(controls_card, fg_color="transparent")
        gain_scale_lbls.pack(fill="x", padx=14, pady=(0, 4))

        ctk.CTkLabel(gain_scale_lbls, text="0% (Mute)", font=ctk.CTkFont(size=9), text_color="#64748b").pack(side="left")
        ctk.CTkLabel(gain_scale_lbls, text="100% (Unity)", font=ctk.CTkFont(size=9), text_color="#64748b").pack(side="left", padx=70)
        ctk.CTkLabel(gain_scale_lbls, text="200% (+6dB)", font=ctk.CTkFont(size=9), text_color="#64748b").pack(side="left", padx=55)
        ctk.CTkLabel(gain_scale_lbls, text="400% (+12dB Boost)", font=ctk.CTkFont(size=9), text_color="#64748b").pack(side="right")

        sep = ctk.CTkFrame(controls_card, height=1, fg_color="#334155")
        sep.pack(fill="x", padx=14, pady=4)

        # B) Left / Right Balance Slider
        balance_header = ctk.CTkFrame(controls_card, fg_color="transparent")
        balance_header.pack(fill="x", padx=14, pady=(6, 2))

        balance_title = ctk.CTkLabel(
            balance_header,
            text="Left / Right Stereo Balance",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#e2e8f0"
        )
        balance_title.pack(side="left")

        self.balance_val_lbl = ctk.CTkLabel(
            balance_header,
            text="Center (L 100% / R 100%)",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#a5b4fc"
        )
        self.balance_val_lbl.pack(side="right")

        balance_slider_row = ctk.CTkFrame(controls_card, fg_color="transparent")
        balance_slider_row.pack(fill="x", padx=14, pady=(2, 4))

        self.balance_slider = ctk.CTkSlider(
            balance_slider_row,
            from_=-1.0,
            to=1.0,
            number_of_steps=40,
            command=self._on_balance_changed,
            progress_color="#6366f1",
            button_color="#818cf8",
            button_hover_color="#a5b4fc"
        )
        self.balance_slider.set(0.0)
        self.balance_slider.pack(side="left", fill="x", expand=True, padx=(0, 10))

        reset_balance_btn = ctk.CTkButton(
            balance_slider_row,
            text="Center",
            width=76,
            height=24,
            font=ctk.CTkFont(size=10),
            fg_color="#334155",
            hover_color="#475569",
            command=self._reset_balance
        )
        reset_balance_btn.pack(side="right")

        balance_scale_lbls = ctk.CTkFrame(controls_card, fg_color="transparent")
        balance_scale_lbls.pack(fill="x", padx=14, pady=(0, 6))

        ctk.CTkLabel(balance_scale_lbls, text="◄ Left 100%", font=ctk.CTkFont(size=10), text_color="#64748b").pack(side="left")
        ctk.CTkLabel(balance_scale_lbls, text="Center", font=ctk.CTkFont(size=10), text_color="#64748b").pack(side="left", padx=140)
        ctk.CTkLabel(balance_scale_lbls, text="Right 100% ►", font=ctk.CTkFont(size=10), text_color="#64748b").pack(side="right")

        sep2 = ctk.CTkFrame(controls_card, height=1, fg_color="#334155")
        sep2.pack(fill="x", padx=14, pady=4)

        # C) Voice Boost Switch (Presence Boost + Rumble Cut)
        voice_row = ctk.CTkFrame(controls_card, fg_color="transparent")
        voice_row.pack(fill="x", padx=14, pady=4)

        voice_info = ctk.CTkFrame(voice_row, fg_color="transparent")
        voice_info.pack(side="left", fill="x", expand=True)

        voice_title = ctk.CTkLabel(
            voice_info,
            text="🎙️ Voice Boost (+8 dB Vocal Presence & Rumble Filter)",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#e2e8f0"
        )
        voice_title.pack(anchor="w")

        voice_desc = ctk.CTkLabel(
            voice_info,
            text="Peaking EQ at 3 kHz cuts through headphone damping; strips low-end AC rumble",
            font=ctk.CTkFont(size=10),
            text_color="#94a3b8"
        )
        voice_desc.pack(anchor="w")

        self.voice_switch = ctk.CTkSwitch(
            voice_row,
            text="",
            width=46,
            command=self._on_voice_boost_toggled,
            progress_color="#10b981",
            button_color="#ecfdf5",
            button_hover_color="#d1fae5"
        )
        self.voice_switch.pack(side="right")

        sep3 = ctk.CTkFrame(controls_card, height=1, fg_color="#334155")
        sep3.pack(fill="x", padx=14, pady=4)

        # D) Buffer Size / Latency Selector
        buffer_row = ctk.CTkFrame(controls_card, fg_color="transparent")
        buffer_row.pack(fill="x", padx=14, pady=(4, 10))

        buffer_lbl = ctk.CTkLabel(
            buffer_row,
            text="⚡ Buffer Size (Latency):",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#94a3b8"
        )
        buffer_lbl.pack(side="left")

        self.blocksize_menu = ctk.CTkSegmentedButton(
            buffer_row,
            values=["32 (0.7 ms)", "64 (1.3 ms)", "128 (2.7 ms)", "256 (5.3 ms)"],
            command=self._on_blocksize_changed,
            selected_color="#0284c7",
            selected_hover_color="#0369a1"
        )
        self.blocksize_menu.set("64 (1.3 ms)")
        self.blocksize_menu.pack(side="right")

        # ----------------- 5. LIVE VU METER -----------------
        meter_card = ctk.CTkFrame(self, corner_radius=12, fg_color="#1e293b")
        meter_card.pack(fill="x", padx=16, pady=(0, 8))

        meter_header = ctk.CTkFrame(meter_card, fg_color="transparent")
        meter_header.pack(fill="x", padx=14, pady=(8, 3))

        meter_title = ctk.CTkLabel(
            meter_header,
            text="Live Passthrough Level",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#94a3b8"
        )
        meter_title.pack(side="left")

        self.meter_db_lbl = ctk.CTkLabel(
            meter_header,
            text="-∞ dB",
            font=ctk.CTkFont(size=11),
            text_color="#64748b"
        )
        self.meter_db_lbl.pack(side="right")

        self.vu_progress = ctk.CTkProgressBar(
            meter_card,
            height=12,
            corner_radius=6,
            progress_color="#10b981",
            fg_color="#0f172a"
        )
        self.vu_progress.set(0.0)
        self.vu_progress.pack(fill="x", padx=14, pady=(0, 10))

        # ----------------- 6. FOOTER -----------------
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(side="bottom", fill="x", padx=16, pady=(0, 8))

        self.hotkey_status_lbl = ctk.CTkLabel(
            footer,
            text="Global Hotkey: Ctrl + Alt + T active",
            font=ctk.CTkFont(size=11),
            text_color="#10b981"
        )
        self.hotkey_status_lbl.pack(side="left")

        brand_lbl = ctk.CTkLabel(
            footer,
            text="Transparency Mode v1.5",
            font=ctk.CTkFont(size=11),
            text_color="#64748b"
        )
        brand_lbl.pack(side="right")

    # ----------------- LOGIC & HANDLERS -----------------

    def refresh_devices(self):
        """Re-scan system audio devices and update dropdown lists with WASAPI priority."""
        inputs, outputs = AudioEngine.get_devices()

        self.input_device_map.clear()
        self.output_device_map.clear()

        input_names = []
        for dev in inputs:
            disp = dev.display_name
            self.input_device_map[disp] = dev
            input_names.append(disp)

        output_names = []
        for dev in outputs:
            disp = dev.display_name
            self.output_device_map[disp] = dev
            output_names.append(disp)

        if not input_names:
            input_names = ["No Input Devices Found"]
        if not output_names:
            output_names = ["No Output Devices Found"]

        self.input_dropdown.configure(values=input_names)
        self.output_dropdown.configure(values=output_names)

        # Smart pre-selection: pick first active WASAPI device
        default_in = input_names[0]
        for name in input_names:
            if "WASAPI" in name:
                default_in = name
                break
        self.input_dropdown.set(default_in)

        default_out = output_names[0]
        wasapi_headphones = [
            name for name in output_names 
            if "WASAPI" in name and any(k in name.lower() for k in ["headphone", "headset", "earphone", "audio"])
        ]
        if wasapi_headphones:
            default_out = wasapi_headphones[0]
        else:
            for name in output_names:
                if "WASAPI" in name:
                    default_out = name
                    break
        self.output_dropdown.set(default_out)

        self._update_latency_display()

    def _get_selected_devices(self) -> Tuple[Optional[AudioDevice], Optional[AudioDevice]]:
        in_name = self.input_dropdown.get()
        out_name = self.output_dropdown.get()
        return self.input_device_map.get(in_name), self.output_device_map.get(out_name)

    def toggle_transparency(self):
        """Toggle audio passthrough on/off."""
        if self.audio_engine.is_running:
            self.audio_engine.stop()
        else:
            in_dev, out_dev = self._get_selected_devices()
            if not in_dev or not out_dev:
                self.status_badge.configure(text="● SELECT DEVICES FIRST", text_color="#ef4444")
                return

            blocksize = self._parse_blocksize(self.blocksize_menu.get())
            success = self.audio_engine.start(in_dev, out_dev, blocksize=blocksize)
            if not success:
                err_msg = self.audio_engine.last_error
                self.status_badge.configure(text="● ERROR STARTING", text_color="#ef4444")
                print(f"[Error] Failed to start audio stream: {err_msg}")

    def _on_engine_status_changed(self, running: bool, message: str):
        """Callback from engine when stream state changes."""
        self.after(0, lambda: self._update_ui_state(running))

    def _update_ui_state(self, running: bool):
        if running:
            self.toggle_btn.configure(
                text="🟢  TRANSPARENCY ACTIVE  (CLICK TO STOP)",
                fg_color="#10b981",
                hover_color="#059669"
            )
            self.status_badge.configure(
                text="● ACTIVE (PASSTHROUGH ON)",
                text_color="#10b981"
            )
            self.input_dropdown.configure(state="disabled")
            self.output_dropdown.configure(state="disabled")
            self.blocksize_menu.configure(state="disabled")
        else:
            self.toggle_btn.configure(
                text="🔊  ACTIVATE TRANSPARENCY MODE",
                fg_color="#2563eb",
                hover_color="#1d4ed8"
            )
            self.status_badge.configure(
                text="● STANDBY",
                text_color="#94a3b8"
            )
            self.input_dropdown.configure(state="normal")
            self.output_dropdown.configure(state="normal")
            self.blocksize_menu.configure(state="normal")
            self.vu_progress.set(0.0)
            self.meter_db_lbl.configure(text="-∞ dB")

        self._update_latency_display()

    def _on_device_changed(self, choice: str):
        """Handle device selection changes."""
        self._update_latency_display()
        if self.audio_engine.is_running:
            in_dev, out_dev = self._get_selected_devices()
            if in_dev and out_dev:
                blocksize = self._parse_blocksize(self.blocksize_menu.get())
                self.audio_engine.start(in_dev, out_dev, blocksize=blocksize)

    def _on_gain_changed(self, value: float):
        self.audio_engine.gain = value
        pct = int(value * 100)
        if pct == 100:
            sub = " (Unity)"
        elif pct > 100:
            db_boost = 20.0 * np.log10(value) if value > 0 else 0
            sub = f" (+{db_boost:.1f} dB)"
        else:
            sub = " (Attenuated)"
        self.gain_val_lbl.configure(text=f"{pct}%{sub}")

    def _set_gain_preset(self, preset_value: float):
        self.gain_slider.set(preset_value)
        self._on_gain_changed(preset_value)

    def _on_balance_changed(self, value: float):
        self.audio_engine.balance = value
        if abs(value) < 0.05:
            self.audio_engine.balance = 0.0
            self.balance_val_lbl.configure(text="Center (L 100% / R 100%)")
        elif value < 0:
            l_pct = 100
            r_pct = int((1.0 + value) * 100)
            self.balance_val_lbl.configure(text=f"◄ Left (L {l_pct}% / R {r_pct}%)")
        else:
            l_pct = int((1.0 - value) * 100)
            r_pct = 100
            self.balance_val_lbl.configure(text=f"Right ► (L {l_pct}% / R {r_pct}%)")

    def _reset_balance(self):
        self.balance_slider.set(0.0)
        self._on_balance_changed(0.0)

    def _on_voice_boost_toggled(self):
        enabled = self.voice_switch.get() == 1
        self.audio_engine.voice_boost = enabled

    def _parse_blocksize(self, val_str: str) -> int:
        if "32" in val_str:
            return 32
        elif "64" in val_str:
            return 64
        elif "128" in val_str:
            return 128
        return 256

    def _on_blocksize_changed(self, value: str):
        bs = self._parse_blocksize(value)
        self.audio_engine.blocksize = bs
        self._update_latency_display()
        if self.audio_engine.is_running:
            in_dev, out_dev = self._get_selected_devices()
            if in_dev and out_dev:
                self.audio_engine.start(in_dev, out_dev, blocksize=bs)

    def _update_latency_display(self):
        rate = self.audio_engine.samplerate or 48000
        bs = self._parse_blocksize(self.blocksize_menu.get())
        ms = (bs / rate) * 1000.0
        self.latency_badge.configure(
            text=f"Buffer: {ms:.1f} ms (WASAPI / {bs} frames)"
        )

    def _setup_global_hotkey(self):
        """Register the global hotkey Ctrl+Alt+T."""
        try:
            keyboard.add_hotkey("ctrl+alt+t", self._on_hotkey_triggered)
            self.hotkey_registered = True
            self.hotkey_status_lbl.configure(
                text="Global Hotkey: Ctrl + Alt + T active",
                text_color="#10b981"
            )
        except Exception as e:
            self.hotkey_registered = False
            self.hotkey_status_lbl.configure(
                text="Global Hotkey registration error",
                text_color="#f59e0b"
            )
            print(f"[Warning] Failed to bind global hotkey: {e}")

    def _on_hotkey_triggered(self):
        self.after(0, self.toggle_transparency)

    def _start_meter_poll(self):
        """Periodic UI update for the VU audio meter."""
        if self.audio_engine.is_running:
            peak = self.audio_engine.current_peak_level
            rms = self.audio_engine.current_rms_level
            display_val = max(peak, rms)
            self.vu_progress.set(display_val)

            if display_val > 0.90:
                self.vu_progress.configure(progress_color="#ef4444")
            elif display_val > 0.70:
                self.vu_progress.configure(progress_color="#f59e0b")
            else:
                self.vu_progress.configure(progress_color="#10b981")

            if display_val > 0.0001:
                db_val = 20.0 * np.log10(display_val)
                self.meter_db_lbl.configure(text=f"{db_val:.1f} dB")
            else:
                self.meter_db_lbl.configure(text="-∞ dB")

        self.after(45, self._start_meter_poll)

    def on_closing(self):
        """Clean teardown on application exit."""
        try:
            if self.hotkey_registered:
                keyboard.unhook_all_hotkeys()
        except Exception:
            pass

        try:
            self.audio_engine.stop()
        except Exception:
            pass

        self.destroy()


if __name__ == "__main__":
    app = TransparencyApp()
    app.mainloop()
