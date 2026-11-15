"""
Transparency Mode - Windows Desktop Application
Built with CustomTkinter, SoundDevice, NumPy, Scipy, and Keyboard.

Allows seamless audio passthrough from microphone to headphones with low latency,
passthrough gain adjustment, voice boost band-pass filtering, and global hotkey control.
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
        self.geometry("540x720")
        self.minsize(500, 680)
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
        # Configure main grid
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        # ----------------- 1. HEADER SECTION -----------------
        header_frame = ctk.CTkFrame(self, corner_radius=12, fg_color="#1e293b")
        header_frame.pack(fill="x", padx=16, pady=(16, 10))

        title_box = ctk.CTkFrame(header_frame, fg_color="transparent")
        title_box.pack(fill="x", padx=16, pady=14)

        title_lbl = ctk.CTkLabel(
            title_box,
            text="🎧 Transparency Mode",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color="#f8fafc"
        )
        title_lbl.pack(anchor="w")

        subtitle_lbl = ctk.CTkLabel(
            title_box,
            text="Ultra-low latency ambient microphone passthrough for headphones",
            font=ctk.CTkFont(size=12),
            text_color="#94a3b8"
        )
        subtitle_lbl.pack(anchor="w", pady=(2, 0))

        # Status & Latency Badges
        badge_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        badge_frame.pack(fill="x", padx=16, pady=(0, 12))

        self.status_badge = ctk.CTkLabel(
            badge_frame,
            text="● STANDBY",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#94a3b8",
            fg_color="#0f172a",
            corner_radius=6,
            padx=10,
            pady=4
        )
        self.status_badge.pack(side="left")

        self.latency_badge = ctk.CTkLabel(
            badge_frame,
            text="Latency: ~5.3 ms (48 kHz / 256 frames)",
            font=ctk.CTkFont(size=11),
            text_color="#cbd5e1",
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
            font=ctk.CTkFont(size=16, weight="bold"),
            height=58,
            corner_radius=12,
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            text_color="#ffffff",
            command=self.toggle_transparency
        )
        self.toggle_btn.pack(fill="x", padx=16, pady=(4, 10))

        # Hotkey indicator under button
        hotkey_hint = ctk.CTkLabel(
            self,
            text="Quick Toggle Hotkey:  Ctrl + Alt + T  (works globally in any app)",
            font=ctk.CTkFont(size=11),
            text_color="#64748b"
        )
        hotkey_hint.pack(pady=(0, 10))

        # ----------------- 3. DEVICE SELECTION CARD -----------------
        device_card = ctk.CTkFrame(self, corner_radius=12, fg_color="#1e293b")
        device_card.pack(fill="x", padx=16, pady=(0, 10))

        card_title_row = ctk.CTkFrame(device_card, fg_color="transparent")
        card_title_row.pack(fill="x", padx=14, pady=(12, 6))

        device_title = ctk.CTkLabel(
            card_title_row,
            text="Audio Devices  (WASAPI Preferred for Lowest Latency)",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#e2e8f0"
        )
        device_title.pack(side="left")

        refresh_btn = ctk.CTkButton(
            card_title_row,
            text="🔄 Refresh",
            width=85,
            height=26,
            font=ctk.CTkFont(size=11),
            fg_color="#334155",
            hover_color="#475569",
            command=self.refresh_devices
        )
        refresh_btn.pack(side="right")

        # Input Microphone Menu
        in_row = ctk.CTkFrame(device_card, fg_color="transparent")
        in_row.pack(fill="x", padx=14, pady=4)

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
            height=32,
            font=ctk.CTkFont(size=11),
            dropdown_font=ctk.CTkFont(size=11),
            fg_color="#0f172a",
            button_color="#334155",
            button_hover_color="#475569"
        )
        self.input_dropdown.pack(side="left", fill="x", expand=True)

        # Output Headphones Menu
        out_row = ctk.CTkFrame(device_card, fg_color="transparent")
        out_row.pack(fill="x", padx=14, pady=(4, 14))

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
            height=32,
            font=ctk.CTkFont(size=11),
            dropdown_font=ctk.CTkFont(size=11),
            fg_color="#0f172a",
            button_color="#334155",
            button_hover_color="#475569"
        )
        self.output_dropdown.pack(side="left", fill="x", expand=True)

        # ----------------- 4. AUDIO CONTROLS CARD -----------------
        controls_card = ctk.CTkFrame(self, corner_radius=12, fg_color="#1e293b")
        controls_card.pack(fill="x", padx=16, pady=(0, 10))

        # Passthrough Gain Slider
        gain_header = ctk.CTkFrame(controls_card, fg_color="transparent")
        gain_header.pack(fill="x", padx=14, pady=(12, 2))

        gain_title = ctk.CTkLabel(
            gain_header,
            text="Passthrough Volume Gain",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#e2e8f0"
        )
        gain_title.pack(side="left")

        self.gain_val_lbl = ctk.CTkLabel(
            gain_header,
            text="100% (1.0x)",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#38bdf8"
        )
        self.gain_val_lbl.pack(side="right")

        slider_row = ctk.CTkFrame(controls_card, fg_color="transparent")
        slider_row.pack(fill="x", padx=14, pady=(2, 6))

        self.gain_slider = ctk.CTkSlider(
            slider_row,
            from_=0.0,
            to=2.0,
            number_of_steps=40,
            command=self._on_gain_changed,
            progress_color="#0284c7",
            button_color="#38bdf8",
            button_hover_color="#7dd3fc"
        )
        self.gain_slider.set(1.0)
        self.gain_slider.pack(side="left", fill="x", expand=True, padx=(0, 10))

        reset_gain_btn = ctk.CTkButton(
            slider_row,
            text="Reset 100%",
            width=80,
            height=26,
            font=ctk.CTkFont(size=11),
            fg_color="#334155",
            hover_color="#475569",
            command=self._reset_gain
        )
        reset_gain_btn.pack(side="right")

        gain_scale_lbls = ctk.CTkFrame(controls_card, fg_color="transparent")
        gain_scale_lbls.pack(fill="x", padx=14, pady=(0, 8))

        ctk.CTkLabel(gain_scale_lbls, text="0% (Mute)", font=ctk.CTkFont(size=10), text_color="#64748b").pack(side="left")
        ctk.CTkLabel(gain_scale_lbls, text="100% (Unity)", font=ctk.CTkFont(size=10), text_color="#64748b").pack(side="left", padx=115)
        ctk.CTkLabel(gain_scale_lbls, text="200% (+6dB Boost)", font=ctk.CTkFont(size=10), text_color="#64748b").pack(side="right")

        sep = ctk.CTkFrame(controls_card, height=1, fg_color="#334155")
        sep.pack(fill="x", padx=14, pady=6)

        # Voice Boost Switch
        voice_row = ctk.CTkFrame(controls_card, fg_color="transparent")
        voice_row.pack(fill="x", padx=14, pady=(6, 4))

        voice_info = ctk.CTkFrame(voice_row, fg_color="transparent")
        voice_info.pack(side="left", fill="x", expand=True)

        voice_title = ctk.CTkLabel(
            voice_info,
            text="🎙️ Voice Boost (Speech Band-Pass Filter)",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#e2e8f0"
        )
        voice_title.pack(anchor="w")

        voice_desc = ctk.CTkLabel(
            voice_info,
            text="Isolates 300Hz–3400Hz voice frequencies; removes HVAC/desk rumble & high hiss",
            font=ctk.CTkFont(size=11),
            text_color="#94a3b8"
        )
        voice_desc.pack(anchor="w")

        self.voice_switch = ctk.CTkSwitch(
            voice_row,
            text="",
            width=50,
            command=self._on_voice_boost_toggled,
            progress_color="#10b981",
            button_color="#ecfdf5",
            button_hover_color="#d1fae5"
        )
        self.voice_switch.pack(side="right")

        sep2 = ctk.CTkFrame(controls_card, height=1, fg_color="#334155")
        sep2.pack(fill="x", padx=14, pady=6)

        # Latency / Blocksize Setting
        buffer_row = ctk.CTkFrame(controls_card, fg_color="transparent")
        buffer_row.pack(fill="x", padx=14, pady=(4, 12))

        buffer_lbl = ctk.CTkLabel(
            buffer_row,
            text="⚡ Buffer Size (Latency):",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#94a3b8"
        )
        buffer_lbl.pack(side="left")

        self.blocksize_menu = ctk.CTkSegmentedButton(
            buffer_row,
            values=["128 (2.7 ms)", "256 (5.3 ms)", "512 (10.7 ms)"],
            command=self._on_blocksize_changed,
            selected_color="#0284c7",
            selected_hover_color="#0369a1"
        )
        self.blocksize_menu.set("256 (5.3 ms)")
        self.blocksize_menu.pack(side="right")

        # ----------------- 5. LIVE VU METER -----------------
        meter_card = ctk.CTkFrame(self, corner_radius=12, fg_color="#1e293b")
        meter_card.pack(fill="x", padx=16, pady=(0, 10))

        meter_header = ctk.CTkFrame(meter_card, fg_color="transparent")
        meter_header.pack(fill="x", padx=14, pady=(10, 4))

        meter_title = ctk.CTkLabel(
            meter_header,
            text="Live Passthrough Level",
            font=ctk.CTkFont(size=12, weight="bold"),
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
            height=14,
            corner_radius=7,
            progress_color="#10b981",
            fg_color="#0f172a"
        )
        self.vu_progress.set(0.0)
        self.vu_progress.pack(fill="x", padx=14, pady=(0, 12))

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
            text="Transparency Mode v1.0",
            font=ctk.CTkFont(size=11),
            text_color="#64748b"
        )
        brand_lbl.pack(side="right")

    # ----------------- LOGIC & HANDLERS -----------------

    def refresh_devices(self):
        """Re-scan system audio devices and update dropdown lists."""
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

        # Smart pre-selection: Pick WASAPI devices first
        # For input: first WASAPI input
        default_in = input_names[0]
        for name in input_names:
            if "WASAPI" in name:
                default_in = name
                break
        self.input_dropdown.set(default_in)

        # For output: prefer WASAPI headphone/headset device
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
        # Use after(0) to update UI safely from any thread
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
            # Restart stream with new device
            in_dev, out_dev = self._get_selected_devices()
            if in_dev and out_dev:
                blocksize = self._parse_blocksize(self.blocksize_menu.get())
                self.audio_engine.start(in_dev, out_dev, blocksize=blocksize)

    def _on_gain_changed(self, value: float):
        self.audio_engine.gain = value
        pct = int(value * 100)
        if pct == 100:
            sub = " (Normal)"
        elif pct > 100:
            db = 20.0 * 0.30103 * (value - 1.0) # approx
            sub = " (Boosted)"
        else:
            sub = " (Attenuated)"
        self.gain_val_lbl.configure(text=f"{pct}%{sub}")

    def _reset_gain(self):
        self.gain_slider.set(1.0)
        self._on_gain_changed(1.0)

    def _on_voice_boost_toggled(self):
        enabled = self.voice_switch.get() == 1
        self.audio_engine.voice_boost = enabled

    def _parse_blocksize(self, val_str: str) -> int:
        if "128" in val_str:
            return 128
        elif "512" in val_str:
            return 512
        return 256

    def _on_blocksize_changed(self, value: str):
        bs = self._parse_blocksize(value)
        self.audio_engine.blocksize = bs
        self._update_latency_display()

    def _update_latency_display(self):
        rate = self.audio_engine.samplerate or 48000
        bs = self._parse_blocksize(self.blocksize_menu.get())
        ms = (bs / rate) * 1000.0
        self.latency_badge.configure(
            text=f"Buffer: {ms:.1f} ms ({rate} Hz / {bs} frames)"
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
        """Executed in background keyboard listener thread."""
        self.after(0, self.toggle_transparency)

    def _start_meter_poll(self):
        """Periodic UI update for the VU audio meter."""
        if self.audio_engine.is_running:
            peak = self.audio_engine.current_peak_level
            rms = self.audio_engine.current_rms_level
            
            # Smooth meter display
            display_val = max(peak, rms)
            self.vu_progress.set(display_val)

            # Change meter color if clipping or near peak
            if display_val > 0.90:
                self.vu_progress.configure(progress_color="#ef4444")
            elif display_val > 0.70:
                self.vu_progress.configure(progress_color="#f59e0b")
            else:
                self.vu_progress.configure(progress_color="#10b981")

            # dB readout
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
